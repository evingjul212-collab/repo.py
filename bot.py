import os
import asyncio
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= DATABASE LOGIC =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "User",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "kondisi": s.get("kondisi") or "Normal",
        "plot": s.get("plot") or "Belum ditentukan",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-30:]) if history else "Mulai."
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_input))
            return resp.text.strip(), m
        except: continue
    return None, None

# ========= HELPERS =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("🗺️ Plot & Kondisi", callback_data="menu_story")],
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all"), InlineKeyboardButton("🎭 Narator", callback_data="step_narator")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("📖 Save/Ekspor", callback_data="export_logs"), InlineKeyboardButton("📂 Load File", callback_data="load_prompt")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await get_state(uid)
    await update.message.reply_text("🎮 RPG Engine V2.8 [Stabil]\nSemua sistem tombol dan karakter telah diperbaiki.", reply_markup=await menu_utama(uid))

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    s = await get_state(uid)
    
    # --- LOAD FILE LOGIC ---
    if update.message.document and s["step"] == "waiting_file":
        file = await update.message.document.get_file()
        byte_content = await file.download_as_bytearray()
        full_text = byte_content.decode("utf-8-sig")
        lines = full_text.splitlines()
        
        new_history, new_chars = [], []
        f_plot, f_kondisi = s["plot"], s["kondisi"]

        for line in lines:
            cl = line.strip()
            if not cl: continue
            if re.search(r'^PLOT:', cl, re.I): f_plot = cl.split(":", 1)[1].strip()
            elif re.search(r'^KONDISI:', cl, re.I): f_kondisi = cl.split(":", 1)[1].strip()
            elif re.search(r'^KARAKTER:', cl, re.I):
                try:
                    core = cl.split(":", 1)[1].strip()
                    sep = "-" if "-" in core else ":"
                    n, d = core.split(sep, 1)
                    new_chars.append({"name": n.strip(), "desc": d.strip()})
                except: continue
            elif re.search(r'^\[.*\]\s*:', cl): new_history.append(cl)

        await save(uid, {"history": new_history if new_history else s["history"], 
                         "chars": new_chars if new_chars else s["chars"], 
                         "plot": f_plot, "kondisi": f_kondisi, "step": None})
        await update.message.reply_text(f"✅ Dimuat: {len(new_history)} baris & {len(new_chars)} NPC.", reply_markup=await menu_utama(uid))
        return

    # --- TEXT INPUT HANDLERS ---
    if s["step"] == "set_plot":
        await save(uid, {"plot": text, "step": None}); await update.message.reply_text("✅ Plot Update.", reply_markup=await menu_utama(uid)); return
    if s["step"] == "updating_kondisi":
        await save(uid, {"kondisi": text, "step": None}); await update.message.reply_text("✅ Kondisi Update.", reply_markup=await menu_utama(uid)); return
    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"}); await update.message.reply_text(f"Deskripsi {text}?"); return
    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None}); await update.message.reply_text("✅ NPC Disimpan.", reply_markup=await menu_utama(uid)); return

    # --- AI PROCESS ---
    if s["step"] in ["action", "narator_input"]:
        is_nar = (s["step"] == "narator_input")
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx].get("desc", "NPC")
        
        system = f"Kamu RPG Engine. Perankan {tag} ({desc}).\nPLOT: {s['plot']}\nKONDISI: {s['kondisi']}"
        prompt = f"POV {tag}: {text}" if not is_nar else f"KEJADIAN: {text}"
        
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, m = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"✨ *{tag}*\n\n{out}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    
    elif q.data == "menu_story":
        kb = [[InlineKeyboardButton("📝 Edit Plot", callback_data="set_plot"), InlineKeyboardButton("📍 Edit Kondisi", callback_data="set_kondisi")], [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]]
        await q.edit_message_text(f"📖 *STORY BIBLE*\n\n*Plot:* {s['plot']}\n*Kondisi:* {s['kondisi']}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]):
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_new"), InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")])
        await q.edit_message_text("Pilih Karakter untuk beraksi:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton(f"💬 Aksi sebagai {name}", callback_data=f"act_{idx}")], [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"selected": idx, "step": "action"})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.message.reply_text(f"Tuliskan aksi/dialog untuk {name}:")

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("Tuliskan kejadian atau narasi baru:")

    elif q.data == "lanjut":
        out, m = await generate("Lanjutkan cerita secara natural.", "Kamu Narator.", s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(f"✨ *NARASI*\n\n{out}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

    elif q.data == "export_logs":
        meta = f"PLOT: {s['plot']}\nKONDISI: {s['kondisi']}\n"
        for c in s["chars"]: meta += f"KARAKTER: {c['name']} - {c['desc']}\n"
        full = f"--- RPG SAVE ---\n{meta}\n--- RIWAYAT ---\n\n" + "\n\n".join(s["history"])
        f = io.BytesIO(full.encode()); f.name = f"Save_{uid}.txt"
        await q.message.reply_document(document=f, caption="File Simpanan Cerita.")

    elif q.data == "load_prompt":
        await save(uid, {"step": "waiting_file"})
        await q.message.reply_text("Silakan kirimkan file .txt hasil ekspor sebelumnya.")

    elif q.data == "add_new":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama NPC baru?")

    elif q.data == "set_plot":
        await save(uid, {"step": "set_plot"})
        await q.message.reply_text("Masukkan Plot/Sinopsis Utama:")

    elif q.data == "set_kondisi":
        await save(uid, {"step": "updating_kondisi"})
        await q.message.reply_text("Masukkan Kondisi/Lokasi saat ini:")

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Baris terakhir dihapus.", reply_markup=await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "plot": "Belum ditentukan", "kondisi": "Normal"})
        await q.message.reply_text("🧹 Database dibersihkan!", reply_markup=await menu_utama(uid))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), msg))
    print("V2.8 Stabilizing Online...")
    app.run_polling()
