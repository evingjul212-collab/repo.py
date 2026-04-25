import os
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId

# --- CONFIG ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# --- DATA INTEGRITY ---
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

# --- ENGINE AI ---
async def generate_response(prompt, history, force_options=False):
    system = ("Penulis RomCom RPG. Fokus interaksi manis."
             "Kamu adalah Penulis Novel Visual RomCom yang ahli dalam dialog interaktif. "
                 "TUGAS: Tulis cerita minimal 1000 karakter. "
                 "GAYA: Perbanyak dialog antar karakter (Gunakan tanda kutip), buat emosional dan sedikit nakal/lucu. "
                 "NARASI: Gunakan narasi hanya untuk aksi fisik atau suasana singkat. "
                  "KARAKTER: Gunakan bahasa gaul/natural.")
    if force_options:
        system += " WAJIB akhiri narasi dengan 4 pilihan aksi: A, B, C, D."
                
    context = "[KONTEKS]\n" + "\n".join(history[-3:]) if history else ""
    full_prompt = f"{system}\n\n{context}\n\n[INPUT]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except: continue
    return None

# --- MENU UTAMA (STANDAR BOSS) ---
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

# --- HANDLER PESAN TEKS ---
async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Halo {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # Proses Edit (Nama -> Deskripsi)
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
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"]})
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Slot '{text}' disimpan!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "action":
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        out = await generate_response(f"Aksi {tag}: {text}", s["history"], False)
        if out:
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"--- {tag} ---\n\n{out}", reply_markup=await menu_utama(uid)); return

    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], True)
        if out:
            s["history"].append(f"[STORY]: {out}"); await save(uid, {"history": s["history"]})
            await update.message.reply_text(f"--- STORY ---\n\n{out}", reply_markup=await menu_utama(uid)); return

# --- HANDLER TOMBOL ---
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    elif q.data == "lanjut":
        # 1. Kasih tanda loading biar Boss gak nunggu tanpa kepastian
        loading_msg = await q.message.reply_text("⏳ Menyusun dialog intens (±1000 karakter)...")
        
        # 2. Prompt diperketat: Dialog dominan + Panjang Teks + Opsi ABCD
        prompt_lanjut = (
            "Lanjutkan alur cerita dengan dialog yang sangat dominan dan emosional. "
            "Tulis teks yang panjangnya SEKITAR 1000 KARAKTER. "
            "Pastikan interaksi antar karakter terasa hidup."
        )
        
        # 3. CRITICAL: Parameter ketiga HARUS 'True' agar muncul ABCD
        out = await generate_response(prompt_lanjut, s["history"], True) 
        
        if out:
            # Hapus pesan loading setelah AI beres mikir
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            
            s["history"].append(f"[STORY]:\n{out}")
            await save(uid, {"history": s["history"]})
            
            # 4. Tampilkan 2 blok (Blok lama + Blok 1000 karakter baru dengan ABCD)
            await tampilkan_dua_blok(uid, context, s)

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): 
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), 
                   InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Daftar Karakter Terdeteksi:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data="act_run")],
              [InlineKeyboardButton("🎬 New Story", callback_data="new_start")],
              [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("edit_"):
        idx = q.data.split("_")[1]
        await save(uid, {"step": f"editname_{idx}"})
        await q.message.reply_text("Masukkan Nama Baru:")

    elif q.data == "new_start":
        idx = s.get("selected", -1); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        out = await generate_response("Mulai pertemuan baru.", [], True)
        if out:
            await save(uid, {"history": [f"[{name}]: {out}"]})
            await q.message.reply_text(f"--- NEW STORY ---\n\n{out}", reply_markup=await menu_utama(uid))

    elif q.data == "save_manual":
        await save(uid, {"step": "save_manual_step"}); await q.message.reply_text("Ketik nama save slot:")

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            history = data.get("history", [])
            # Sinkronisasi data ke state aktif
            await save(uid, {
                "history": history,
                "chars": data.get("chars", []),
                "name": data.get("name"),
                "step": None
            })
            
            # --- LOGIKA TAMPILKAN 1 BLOK CERITA ---
            if history:
                pesan_terakhir = history[-1] # Ambil baris paling akhir di history
                teks_tampilan = f"✅ **GAME LOADED**\n\nRiwayat Terakhir:\n{pesan_terakhir}"
            else:
                teks_tampilan = "✅ **GAME LOADED**\n\n(Belum ada riwayat cerita di slot ini)"

            # Kirim pesan cerita terakhir + Menu Utama
            await q.message.reply_text(teks_tampilan, reply_markup=await menu_utama(uid))

    elif q.data == "act_run": await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi:")
    elif q.data == "undo" and s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Back.")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "reset_confirm": await save(uid, {"step": "set_name", "history": [], "chars": []}); await q.message.reply_text("Reset! Namamu?")

# --- FUNGSI START ---
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": []}) 
    await update.message.reply_text("Siapa namamu?")
#==========================
# funsi tetap tampilkan cerita 
async def tampilkan_dua_blok(uid, context, s):
    history = s.get("history", [])
    if len(history) >= 2:
        # Ambil 2 terakhir
        teks = f"{history[-2]}\n\n{history[-1]}"
    elif len(history) == 1:
        teks = history[-1]
    else:
        teks = "📖 Belum ada cerita. Mulailah petualanganmu!"
    
    # Kirim sebagai PESAN BARU (bukan edit) agar tidak hilang
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))

# --- BAGIAN RUNNING ---
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    
    print("✅ Bot sudah diperbaiki dan siap jalan!")
    app.run_polling(drop_pending_updates=True)
