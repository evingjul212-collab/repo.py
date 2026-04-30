import os 
import asyncio
import re 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId 

# =================================================================
# [1] CONFIG & DATABASE CONNECTION
# =================================================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.datsa

# =================================================================
# [2] DATA MANAGEMENT (SAVE/GET STATE)
# =================================================================
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name", "User"),
        "desc_utama": s.get("desc_utama", "Tokoh Utama"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []), # Nanti di sini tiap NPC punya field 'mood'
        "selected": s.get("selected", -1),
        "world_state": s.get("world_state", {"time": "Pagi", "location": "Rumah", "turn": 0}), 
        "summary": s.get("summary", ""), 
        "temp_val": s.get("temp_val")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    return fix_state(s)

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# =================================================================
# [3] UI HELPERS (MESSAGE RENDERING) - FIX MESSAGE TOO LONG
# =================================================================
async def tampilkan_blok_terbaru(uid, context, s):
    history = s.get("history", [])
    teks = history[-1] if history else "📖 Belum ada cerita. Mulailah petualanganmu!"
    
    if len(teks) > 4000:
        teks = teks[:3900] + "...\n\n(Teks terpotong karena terlalu panjang)"
        
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))

async def tampilkan_dua_blok(uid, context, s):
    history = s.get("history", [])
    if len(history) >= 2:
        teks = f"{history[-2]}\n\n{'-'*20}\n\n{history[-1]}"
    elif len(history) == 1:
        teks = history[-1]
    else:
        teks = "📖 Belum ada cerita. Mulailah petualanganmu!"
    
    if len(teks) > 4000:
        teks = f"(Cerita sebelumnya disembunyikan karena terlalu panjang)\n\n{'-'*20}\n\n{history[-1]}"
        if len(teks) > 4000: teks = teks[:3900] + "..." 
        
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))

# =================================================================
# [4] AI CORE ENGINE - UPGRADE LEVEL (MOOD, TIME, MEMORY)
# =================================================================
async def generate_response(prompt, history, s, force_options=False):
    waktu = s["world_state"]["time"]
    lokasi = s["world_state"]["location"]
    
    idx = s.get("selected", -1)
    npc_info = ""
    if idx != -1:
        npc = s["chars"][idx]
        mood = npc.get("mood", 50) 
        npc_info = f"NPC SAAT INI: {npc['name']} (Mood: {mood}/100)."
    
    system = (
        f"Kamu adalah Penulis Novel Visual Dewasa/RomCom.\n"
        f"RINGKASAN CERITA LALU: {s.get('summary', 'Baru dimulai')}\n"
        f"DUNIA SAAT INI: {waktu} di {lokasi}.\n"
        f"{npc_info}\n\n"
        "ATURAN LEVEL UP:\n"
        "1. MOOD & LOVE: NPC hanya akan merespon godaan/ajakan bercinta jika Mood > 80 DAN lokasi bersifat privat (seperti Kamar atau Rumah) DAN waktu Malam.\n"
        "2. Jika Mood < 40, NPC akan bersikap dingin atau marah.\n"
        "3. Jika waktu Malam, suasana harus lebih romantis atau tegang.\n"
        "4. KONSISTENSI: Baca ringkasan cerita agar tidak lupa kejadian penting sebelumnya.\n"
        "5. Tulis cerita ±1000 karakter dengan narasi suasana yang menggoda dan dialog intens."
    )
    
    if force_options:
        system += "\nWAJIB akhiri dengan 4 pilihan aksi: A, B, C, D."
    
    context = "\n".join(history[-3:]) if history else "Cerita baru dimulai."
    full_prompt = f"{system}\n\n{context}\n\n[INSTRUKSI SAAT INI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except: continue
    return None

# =================================================================
# [5] KEYBOARD MENUS
# =================================================================
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")], 
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), 
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")], 
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"), 
         InlineKeyboardButton("📂 Load Slot", callback_data="load_list")], 
        [InlineKeyboardButton("📖 Riwayat", callback_data="show_history"), 
         InlineKeyboardButton("↩️ Back", callback_data="undo")], 
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), 
         InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")] 
    ]
    return InlineKeyboardMarkup(kb)

# =================================================================
# [6] TEXT MESSAGE HANDLER (LOGIC BY STEP)
# =================================================================
async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Halo {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_val": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Sekarang masukkan DESKRIPSI baru:"); return
    
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_val"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_val"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text("✨ Karakter diperbarui!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "save_manual_step":
        save_data = {"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s.get("desc_utama", "Tokoh Utama")}
        await archives.insert_one(save_data)
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Slot '{text}' berhasil disimpan!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "action":
        tag = s["name"] if s.get("selected", -1) == -1 else s["chars"][s["selected"]]["name"]
        out = await generate_response(f"Aksi {tag}: {text}", s["history"], s, False)
        if out:
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"--- {tag} ---\n\n{out}", reply_markup=await menu_utama(uid)); return

    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]: {out}"); await save(uid, {"history": s["history"]})
            await tampilkan_dua_blok(uid, context, s); return

    if s["step"] == "add_npc_name":
        await save(uid, {"temp_val": text, "step": "add_npc_desc"})
        await update.message.reply_text(f"Nama: **{text}**\n\nSekarang masukkan **Deskripsi** NPC tersebut:"); return

    if s["step"] == "add_npc_desc":
        new_npc = {"name": s["temp_val"], "desc": text}
        s["chars"].append(new_npc)
        await save(uid, {"chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text(f"✅ NPC **{new_npc['name']}** ditambahkan!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "narator_input":
        loading_msg = await update.message.reply_text("✍️ Narator sedang menyusun cerita...")
        is_new = len(s["history"]) == 0
        prompt_narator = f"Bertindaklah sebagai Narator. Arahan: '{text}', {'buat pembukaan' if is_new else 'lanjutkan alur'}. Target ±1000 karakter."
        out = await generate_response(prompt_narator, s["history"], s, True)
        if out:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            s["history"].append(f"[NARRATOR]:\n{out}")
            s = update_mood(s, text if 'text' in locals() else "")
            s = update_memory(s, s["history"][-1])
            s["world_state"] = update_world(s)
            await update_summary(uid, s)
            await save(uid, {
            "history": s["history"],
            "chars": s["chars"],
            "world_state": s["world_state"],
            "memory": s.get("memory", []),
            "summary": s.get("summary", "")
            })

            await save(uid, {"history": s["history"], "step": None})
            await tampilkan_blok_terbaru(uid, context, s)
        return

# =================================================================
# [7] CALLBACK QUERY HANDLER (BUTTON LOGIC)
# =================================================================
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "lanjut":
        loading_msg = await q.message.reply_text("⏳ Menyusun dialog intens...")
        out = await generate_response("Lanjutkan alur cerita, ±1000 karakter.", s["history"], s, True) 
        if out:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            s["history"].append(f"[STORY]:\n{out}");
            s = update_mood(s, text if 'text' in locals() else "")
            s = update_memory(s, s["history"][-1])
            s["world_state"] = update_world(s)
            await update_summary(uid, s)
            await save(uid, {
            "history": s["history"],
            "chars": s["chars"],
            "world_state": s["world_state"],
            "summary": s.get("summary", "")
            })

            await save(uid, {"history": s["history"]})
            await tampilkan_blok_terbaru(uid, context, s)

    elif q.data == "add_npc":
        await save(uid, {"step": "add_npc_name"})
        await q.message.reply_text("👤 **Tambah NPC Baru**\n\nMasukkan **Nama** NPC:")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.message.reply_text("📋 **Daftar Karakter:**", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"selected": idx})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s.get("desc_utama") if idx == -1 else s["chars"][idx].get("desc")
        
        if idx != -1:
            mood = s["chars"][idx].get("mood", 50)
            heart_icons = "❤️" * (mood // 20) + "🤍" * (5 - (mood // 20))
            status_mood = f"{heart_icons} ({mood}/100)"
        else:
            status_mood = "🌟 (Pemain Utama)"

        teks_tampilan = (
            f"👤 **PROFIL KARAKTER**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📛 **Nama:** {name}\n"
            f"🎭 **Role:** {'Tokoh Utama' if idx == -1 else 'NPC'}\n"
            f"💓 **Mood:** {status_mood}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📖 **Deskripsi:**\n_{desc}_\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *Tips: Mood > 80 di malam hari membuka interaksi spesial.*"
        )

        kb = [
            [InlineKeyboardButton("🎮 Aksi", callback_data="act_run")],
            [InlineKeyboardButton("🎬 New Story", callback_data="new_start")],
            [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
        ]
        try: await q.edit_message_text(teks_tampilan, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except: await q.message.reply_text(teks_tampilan, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif q.data == "save_manual": await save(uid, {"step": "save_manual_step"}); await q.message.reply_text("💾 Ketik nama Save Slot:")
    elif q.data.startswith("edit_"): idx = q.data.split("_")[1]; await save(uid, {"step": f"editname_{idx}"}); await q.message.reply_text("Masukkan Nama Baru:")
    
    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        save_id_str = q.data.split("_")[1]
        try:
            data_save = await archives.find_one({"_id": ObjectId(save_id_str)})
        except:
            data_save = await archives.find_one({"_id": save_id_str})

        if data_save:
            data_siap = fix_state(data_save)
            data_siap["_id"] = uid 
            await save(uid, data_siap)
            await q.message.reply_text(f"✅ Berhasil memuat simpanan: {data_save.get('save_name', 'Tanpa Nama')}")
            await tampilkan_dua_blok(uid, context, data_siap)
        else:
            await q.message.reply_text("❌ Waduh, filenya gak ketemu atau rusak, Boss!")

    elif q.data == "new_start":
        idx = s.get("selected", -1); loading_msg = await q.message.reply_text("🎬 Menyiapkan skenario...")
        if idx == -1:
            prompt = f"Mulai cerita baru POV {s['name']}. Narasi suasana. Pilih HANYA SATU NPC relevan dari daftar. NPC lain dilarang muncul."
        else:
            n = s["chars"][idx]["name"]; d = s["chars"][idx].get("desc", "")
            prompt = f"Mulai cerita baru. Fokus interaksi {s['name']} dengan {n} ({d}). Narasi suasana. DILARANG munculkan NPC lain."
        out = await generate_response(prompt, [], s, True)
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            new_h = [f"[STORY]:\n{out}"]; await save(uid, {"history": new_h}); await tampilkan_blok_terbaru(uid, context, {"history": new_h})

    elif q.data == "act_run": await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi:")
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Undo."); await tampilkan_blok_terbaru(uid, context, s)
    elif q.data == "reset_confirm": await save(uid, {"step": "set_name", "history": [], "chars": []}); await q.message.reply_text("Reset! Namamu?")
    elif q.data == "main_menu": await q.message.reply_text("📱 **Menu Utama:**", reply_markup=await menu_utama(uid))
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Ketik alur cerita (awal/lanjutan):")
    elif q.data == "regen":
        if not s["history"]: return
        loading_msg = await q.message.reply_text("🔄 Menulis ulang...")
        s["history"].pop(); out = await generate_response("Ulangi adegan terakhir, ±1000 karakter.", s["history"], s, True)
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            s["history"].append(f"[STORY]:\n{out}"); 
            s = update_mood(s, text if 'text' in locals() else "")
s = update_memory(s, s["history"][-1])
s["world_state"] = update_world(s)
await update_summary(uid, s)
await save(uid, {
    "history": s["history"],
    "chars": s["chars"],
    "world_state": s["world_state"],
    "memory": s.get("memory", []),
    "summary": s.get("summary", "")
})

            await save(uid, {"history": s["history"]}); await tampilkan_blok_terbaru(uid, context, s)

# =================================================================
# [7.5] CONTEXT MANAGEMENT
# =================================================================
async def update_summary(uid, s):
    if len(s["history"]) > 10:
        p = f"Buat ringkasan super singkat (1 paragraf) dari riwayat ini agar poin penting tidak terlupa: \n" + "\n".join(s["history"])
        summary = await generate_response(p, [], s, False)
        if summary:
            await save(uid, {"summary": summary, "history": s["history"][-3:]})

# =================================================================
# [8] MAIN RUNNER (POLLING)
# =================================================================
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": []}) 
    await update.message.reply_text("ini versi baru, Siapa namamu?")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    async def main():
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Koneksi lama dibersihkan. Memulai polling...")
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)A
            while True: await asyncio.sleep(1000)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("👋 Bot dimatikan.")
