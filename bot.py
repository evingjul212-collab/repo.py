#==============

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
archives = db.archives 

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
def clean_text(teks):
    return teks.replace("[STORY]:", "").replace("[NARRATOR]:", "").strip()

async def tampilkan_blok_terbaru(uid, context, s):
    history = s.get("history", [])
    teks = history[-1] if history else "📖 Belum ada cerita. Mulailah petualanganmu!"

    teks = clean_text(teks)

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
    
    # FIX: Batasi panjang total teks gabungan agar tidak crash
    if len(teks) > 4000:
        # Jika gabungan terlalu panjang, tampilkan yang paling baru saja
        teks = f"(Cerita sebelumnya disembunyikan karena terlalu panjang)\n\n{'-'*20}\n\n{history[-1]}"
        if len(teks) > 4000: teks = teks[:3900] + "..." # Jaga-jaga kalau 1 blok saja sudah 4000
        
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))

# =================================================================
# [4] AI CORE ENGINE (GENERATOR) - ANTI-META DATA PEAKING
# =================================================================
async def generate_response(prompt, history, s, force_options=False):
    pov_name = s["name"] if s.get("selected", -1) == -1 else s["chars"][s["selected"]]["name"]
    
    system = (
        f"Kamu adalah Penulis Novel dewasa Interaktif yang ahli dalam dialog intens.\n"
        f"FOKUS POV: {pov_name} (Gunakan kata ganti 'Aku').\n\n"
        "ATURAN DIALOG & INTERAKSI:\n"
        "- PERBANYAK DIALOG antar karakter. Buat percakapan yang terasa hidup dan reaktif.\n"
        "- Fokus pada ketegangan verbal, godaan, atau konflik dalam percakapan.\n"
        "- Kurangi narasi deskripsi lingkungan yang panjang; fokus pada gerakan tubuh saat berbicara (body language).\n"
        "- Setiap tindakan 'Aku' harus memicu respon langsung dari karakter lawan bicara.\n"
    )
    
    if force_options:
        system += "\nWAJIB akhiri dengan 4 pilihan aksi (A, B, C, D) yang memicu kelanjutan dialog."
    
    context = "\n".join(history[-3:]) if history else "Cerita baru dimulai."
    full_prompt = f"{system}\n\n[KONTEKS TERAKHIR]\n{context}\n\n[INSTRUKSI AKSI SEKARANG]\n{prompt}"

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

    # --- STEP: NAMA AWAL ---
    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Halo {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # --- STEP: EDIT KARAKTER (NAMA) ---
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_val": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Sekarang masukkan DESKRIPSI baru:"); return
    
    # --- STEP: EDIT KARAKTER (DESKRIPSI) ---
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_val"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_val"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text("✨ Karakter diperbarui!", reply_markup=await menu_utama(uid)); return

    # --- STEP: SAVE MANUAL (NAMA SLOT) ---
    if s["step"] == "save_manual_step":
        save_data = {"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s.get("desc_utama", "Tokoh Utama")}
        await archives.insert_one(save_data)
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Slot '{text}' berhasil disimpan!", reply_markup=await menu_utama(uid)); return

      # --- STEP: ACTION (INPUT BEBAS) ---
    if s["step"] == "action":
        # Tentukan tag nama (User Utama atau NPC)
        tag = s["name"] if s.get("selected", -1) == -1 else s["chars"][s["selected"]]["name"]
        
        loading_msg = await update.message.reply_text(f"⏳ {tag} sedang bertindak...")
        
        out = await generate_response(f"Lanjutkan dialog intens antara {tag} dan karakter lawan. "
        f"{tag} melakukan: {text}. Buat percakapan yang romatis dewasa dan responsif.", 
        s["history"],, s, True)
        
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass

            # Format hasil akhir dengan Header dan Tag sesuai permintaanmu
            formatted_story = f"--- {tag} ---\n\n[{tag}]: {out}"
            
            # Simpan ke history (tanpa header dekoratif agar konteks AI tetap bersih)
            s["history"].append(f"[{tag}]: {out}")
            
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(formatted_story, reply_markup=await menu_utama(uid))
            return

    # --- STEP: NARATOR ---
    if s["step"] == "narator_input":
        loading_msg = await update.message.reply_text("✍️ Narator sedang menyusun cerita...")
        is_new = len(s["history"]) == 0
        
        prompt_narator = (
            f"Lanjutkan cerita berdasarkan input user berikut:\n{text}\n\n"
            + ("Buat pembukaan cerita." if is_new else "WAJIB lanjut dari cerita terakhir, JANGAN ulang dari awal.")
        )
        out = await generate_response(prompt_narator, s["history"], s, True)

        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass

            s["history"].append(out)
            # s["step"] = "narator_input"  # Tetap di mode narator (opsional)
            await save(uid, {"history": s["history"], "step": "narator_input"}) # Lu lupa save step/history di sini
            await update.message.reply_text(out, reply_markup=await menu_utama(uid))
        return

    # --- STEP: PILIHAN A/B/C/D ---
    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], s, True)
        if out:
            s["history"].append(out); await save(uid, {"history": s["history"]})
            await tampilkan_dua_blok(uid, context, s); return

    # --- STEP: TAMBAH NPC (NAMA) ---
    if s["step"] == "add_npc_name":
        await save(uid, {"temp_val": text, "step": "add_npc_desc"})
        await update.message.reply_text(f"Nama: **{text}**\n\nSekarang masukkan **Deskripsi** NPC tersebut:"); return

    # --- STEP: TAMBAH NPC (DESKRIPSI) ---
    if s["step"] == "add_npc_desc":
        new_npc = {"name": s["temp_val"], "desc": text}
        s["chars"].append(new_npc)
        await save(uid, {"chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text(f"✅ NPC **{new_npc['name']}** ditambahkan!", reply_markup=await menu_utama(uid)); return

# --- STEP: NARATOR ---
# ================= NARATOR =================
    if s["step"] == "narator_input":
        loading_msg = await update.message.reply_text("✍️ Narator sedang menyusun cerita...")

        is_new = len(s["history"]) == 0

    prompt_narator = (
        f"Lanjutkan cerita berdasarkan input user berikut:\n{text}\n\n"
        + ("Buat pembukaan cerita." if is_new else "WAJIB lanjut dari cerita terakhir, JANGAN ulang dari awal.")
    )

    out = await generate_response(prompt_narator, s["history"], s, True)

    if out:
        try:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
        except:
            pass

        # simpan TANPA tag aneh
        s["history"].append(out)

        # 🔥 PENTING: JANGAN MATIKAN MODE
        s["step"] = "narator_input"

        s = await apply_updates(uid, s, text)

        await update.message.reply_text(out, reply_markup=await menu_utama(uid))
    return

    # fallback
    await update.message.reply_text(
        "Pilih menu dulu.",
        reply_markup=await menu_utama(uid)
    )
# =================================================================
# [7] CALLBACK QUERY HANDLER (BUTTON LOGIC)
# =================================================================
async def callback(update, context):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    try: await q.answer()
    except:  pass
    # --- TOMBOL: LANJUT ---
        if q.data == "lanjut":
        # Tentukan siapa POV yang sedang aktif
        tag = s["name"] if s.get("selected", -1) == -1 else s["chars"][s["selected"]]["name"]
        
        loading_msg = await q.message.reply_text(f"⏳ {tag} melanjutkan pembicaraan...")
        
        # Instruksi khusus untuk "Lanjut": Fokus pada perkembangan dialog dan respon lawan bicara
        prompt_lanjut = (
            f"Lanjutkan adegan ini secara natural. Fokus pada interaksi dialog yang lebih dalam "
            f"dan reaksi emosional antara {tag} dan karakter di hadapannya. "
            f"Jangan biarkan cerita berhenti, buat suasana semakin intens."
        )
        
        out = await generate_response(prompt_lanjut, s["history"], s, True) 
        
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            
            # Format dengan header dan tag POV seperti permintaanmu
            formatted_story = f"--- {tag} ---\n\n[{tag}]: {out}"
            
            # Simpan ke history
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"]})
            
            # Tampilkan pesan terbaru dengan format yang sudah rapi
            await q.message.reply_text(formatted_story, reply_markup=await menu_utama(uid))

    # --- TOMBOL: TAMBAH NPC ---
    elif q.data == "add_npc":
        await save(uid, {"step": "add_npc_name"})
        await q.message.reply_text("👤 **Tambah NPC Baru**\n\nMasukkan **Nama** NPC:")

    # --- TOMBOL: LIST KARAKTER ---
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.message.reply_text("📋 **Daftar Karakter:**", reply_markup=InlineKeyboardMarkup(kb))

    # --- TOMBOL: DETAIL KARAKTER (SELECTED) ---
    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s.get("desc_utama") if idx == -1 else s["chars"][idx].get("desc")
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data="act_run")], [InlineKeyboardButton("🎬 New Story", callback_data="new_start")], [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")], [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"👤 **Detail Karakter**\n━━━━━━━━━━━━━━━\n📛 **Nama:** {name}\n📖 **Deskripsi:**\n{desc}", reply_markup=InlineKeyboardMarkup(kb))

    # --- TOMBOL: SAVE/LOAD/EDIT ---
    elif q.data == "save_manual": await save(uid, {"step": "save_manual_step"}); await q.message.reply_text("💾 Ketik nama Save Slot:")
    elif q.data.startswith("edit_"): idx = q.data.split("_")[1]; await save(uid, {"step": f"editname_{idx}"}); await q.message.reply_text("Masukkan Nama Baru:")
    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            s_new = {"history": data.get("history", []), "chars": data.get("chars", []), "name": data.get("name"), "desc_utama": data.get("desc_utama"), "step": None}
            await save(uid, s_new); await q.message.reply_text("✅ LOAD SUCCESS!"); await tampilkan_dua_blok(uid, context, s_new)

    # --- TOMBOL: NEW STORY (LOGIKA NPC EKSKLUSIF) ---
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

    # --- TOMBOL: AKSI/UNDO/RESET ---
    elif q.data == "act_run": await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi:")
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Undo."); await tampilkan_blok_terbaru(uid, context, s)
    elif q.data == "reset_confirm": await save(uid, {"step": "set_name", "history": [], "chars": []}); await q.message.reply_text("Reset! Namamu?")
    elif q.data == "main_menu": await q.message.reply_text("📱 **Menu Utama:**", reply_markup=await menu_utama(uid))

    # --- TOMBOL: NARATOR & REGEN ---
    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 Ketik alur cerita (awal/lanjutan):")

    elif q.data == "regen":
        if not s["history"]: return
        loading_msg = await q.message.reply_text("🔄 Menulis ulang...")
        s["history"].pop(); out = await generate_response("Ulangi adegan terakhir, ±1000 karakter.", s["history"], s, True)
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            s["history"].append(f"[STORY]:\n{out}"); await save(uid, {"history": s["history"]}); await tampilkan_blok_terbaru(uid, context, s)

# =================================================================
# [8] MAIN RUNNER (POLLING) - FIX CONFLICT ERROR
# =================================================================
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": []}) 
    await update.message.reply_text("Siapa namamu?")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Handler tetap sama
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    # --- LOGIKA ANTI CONFLICT ---
    async def main():
        # 1. Hapus webhook dan drop pesan yang pending (biar bot gak kaget pas nyala)
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Koneksi lama dibersihkan. Memulai polling...")
        
        # 2. Jalankan polling
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            
            # Biar bot tetap nyala terus
            while True:
                await asyncio.sleep(1000)

    # Jalankan dengan loop utama
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("👋 Bot dimatikan.")
