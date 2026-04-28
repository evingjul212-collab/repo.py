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
        "chars": s.get("chars", []), 
        "selected": s.get("selected", -1),
        "world_state": s.get("world_state", {"time": "Pagi", "location": "Rumah", "turn": 0}), 
        "summary": s.get("summary", ""), 
        "temp_val": s.get("temp_val"),
        # Field baru untuk mendukung fitur regen yang akurat [cite: 7]
        "last_prompt": s.get("last_prompt", ""), 
        "last_was_forced": s.get("last_was_forced", False)
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    return fix_state(s)

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# =================================================================
# [3] UI HELPERS (MESSAGE RENDERING)
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
# [4] AI CORE ENGINE
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
        "1. MOOD & LOVE: NPC hanya akan merespon godaan/ajakan bercinta jika Mood > 80 DAN lokasi bersifat privat DAN waktu Malam.\n"
        "2. Jika Mood < 40, NPC akan bersikap dingin atau marah.\n"
        "3. Jika waktu Malam, suasana harus lebih romantis.\n"
        "4. KONSISTENSI: Baca ringkasan cerita agar tidak lupa kejadian penting.\n"
        "5. Tulis cerita ±1000 karakter dengan narasi menggoda dan dialog intens."
    )
    
    if force_options:
        system += "\nWAJIB akhiri dengan 4 pilihan aksi: A, B, C, D."
    
    context_chat = "\n".join(history[-3:]) if history else "Cerita baru dimulai."
    full_prompt = f"{system}\n\n{context_chat}\n\n[INSTRUKSI SAAT INI]\n{prompt}"

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
# [6] TEXT MESSAGE HANDLER
# =================================================================
async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Halo {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "action":
        tag = s["name"] if s.get("selected", -1) == -1 else s["chars"][s["selected"]]["name"]
        prompt_teks = f"Aksi {tag}: {text}" # Simpan prompt untuk regen [cite: 11]
        out = await generate_response(prompt_teks, s["history"], s, False)
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {
                "history": s["history"], 
                "step": None,
                "last_prompt": prompt_teks, # [cite: 8, 14]
                "last_was_forced": False
            })
            await update.message.reply_text(f"--- {tag} ---\n\n{out}", reply_markup=await menu_utama(uid)); return

    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        prompt_teks = f"Pilih {text.upper()}"
        out = await generate_response(prompt_teks, s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]: {out}")
            await save(uid, {
                "history": s["history"],
                "last_prompt": prompt_teks, # [cite: 8, 14]
                "last_was_forced": True
            })
            await tampilkan_dua_blok(uid, context, s); return

    if s["step"] == "narator_input":
        loading_msg = await update.message.reply_text("✍️ Narator sedang menyusun...")
        is_new = len(s["history"]) == 0
        prompt_narator = f"Bertindaklah sebagai Narator. Arahan: '{text}', {'buat pembukaan' if is_new else 'lanjutkan alur'}."
        out = await generate_response(prompt_narator, s["history"], s, True)
        if out:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            s["history"].append(f"[NARRATOR]:\n{out}")
            await save(uid, {
                "history": s["history"], 
                "step": None,
                "last_prompt": prompt_narator, # [cite: 8, 14]
                "last_was_forced": True
            })
            await tampilkan_blok_terbaru(uid, context, s)
        return

    # Logika edit karakter & save (disingkat demi struktur)
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_val": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Masukkan DESKRIPSI:"); return
    
    if s["step"] == "save_manual_step":
        save_data = {"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"]}
        await archives.insert_one(save_data)
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Tersimpan: {text}", reply_markup=await menu_utama(uid)); return

# =================================================================
# [7] CALLBACK QUERY HANDLER
# =================================================================
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "lanjut":
        loading_msg = await q.message.reply_text("⏳ Menyusun...")
        prompt_teks = "Lanjutkan alur cerita, ±1000 karakter." # [cite: 10]
        out = await generate_response(prompt_teks, s["history"], s, True) 
        if out:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            s["history"].append(f"[STORY]:\n{out}")
            await save(uid, {
                "history": s["history"],
                "last_prompt": prompt_teks, # [cite: 8, 14]
                "last_was_forced": True
            })
            await tampilkan_blok_terbaru(uid, context, s)

    elif q.data == "regen":
        if not s["history"] or not s.get("last_prompt"): 
            await q.message.reply_text("❌ Tidak ada data untuk di-regen.")
            return
            
        loading_msg = await q.message.reply_text("🔄 Menulis ulang adegan terakhir...")
        s["history"].pop() # Buang hasil yang "jelek" [cite: 9]
        
        # Ambil instruksi asli yang terakhir kali dikirim [cite: 9, 10]
        out = await generate_response(s["last_prompt"], s["history"], s, s["last_was_forced"])
        
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            
            tag = "[STORY]:" if s["last_was_forced"] else "[REACTION]:" 
            s["history"].append(f"{tag}\n{out}")
            await save(uid, {"history": s["history"]})
            await tampilkan_blok_terbaru(uid, context, s)

    elif q.data == "new_start":
        idx = s.get("selected", -1)
        loading_msg = await q.message.reply_text("🎬 Skenario baru...")
        if idx == -1: prompt = f"Mulai cerita baru POV {s['name']}."
        else: prompt = f"Mulai cerita baru interaksi {s['name']} dengan {s['chars'][idx]['name']}."
        
        out = await generate_response(prompt, [], s, True)
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            new_h = [f"[STORY]:\n{out}"]
            await save(uid, {
                "history": new_h, 
                "last_prompt": prompt, # [cite: 8, 14]
                "last_was_forced": True
            })
            await tampilkan_blok_terbaru(uid, context, {"history": new_h})

    # Callback lainnya (list_all, sel_, undo, dll) tetap sama
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.message.reply_text("📋 Daftar Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Undo."); await tampilkan_blok_terbaru(uid, context, s)
    elif q.data == "reset_confirm": await save(uid, {"step": "set_name", "history": [], "chars": []}); await q.message.reply_text("Reset! Namamu?")
    elif q.data == "act_run": await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi:")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Ketik alur:")

# =================================================================
# [8] MAIN RUNNER
# =================================================================
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": [], "last_prompt": ""}) 
    await update.message.reply_text("Selamat datang! Siapa namamu?")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    async def main():
        await app.bot.delete_webhook(drop_pending_updates=True)
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            while True: await asyncio.sleep(1000)

    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): pass
