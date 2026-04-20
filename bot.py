import os
import asyncio
import io
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
        "plot": s.get("plot") or "Belum ditentukan", # FITUR BARU: Sinopsis/Plot
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
    # Mengambil 25 baris history untuk konteks
    context = "\n---\n".join(history[-25:]) if history else "Mulai."
    full_input = f"{system}\n\n[MEMORI CERITA]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
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
        [InlineKeyboardButton("🗺️ Alur/Plot & Kondisi", callback_data="menu_story")],
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all"), InlineKeyboardButton("🎭 Narator", callback_data="step_narator")],
        [InlineKeyboardButton("⏩ Lanjut Alur", callback_data="lanjut"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("📖 Baca/Ekspor", callback_data="export_logs"), InlineKeyboardButton("📂 Load File", callback_data="load_prompt")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(update, text, tag, markup):
    try:
        await update.message.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await update.message.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Langsung munculkan menu tanpa tanya nama
    await get_state(uid) 
    await update.message.reply_text("🎮 RPG Engine V2.3\nSiap melanjutkan petualangan?", reply_markup=await menu_utama(uid))

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    s = await get_state(uid)
    
    # Logic Load File (Menerima file .txt)
    if update.message.document and s["step"] == "waiting_file":
        file = await update.message.document.get_file()
        content = await file.download_as_bytearray()
        decoded = content.decode("utf-8").split("\n\n")
        # Membersihkan header "RIWAYAT" jika ada
        cleaned_history = [line for line in decoded if "]: " in line]
        await save(uid, {"history": cleaned_history, "step": None})
        await update.message.reply_text(f"✅ Berhasil memuat {len(cleaned_history)} baris cerita!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "set_plot":
        await save(uid, {"plot": text, "step": None})
        await update.message.reply_text("✅ Sinopsis/Plot diperbarui!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "updating_kondisi":
        await save(uid, {"kondisi": text, "step": None})
        await update.message.reply_text(f"✅ Kondisi diperbarui!", reply_markup=await menu_utama(uid))
        return

    # ... (Handler Nama Karakter, Import Massal, dan Update Karakter sama seperti V2.2) ...
    if s["step"] == "import_chars":
        lines = text.split("\n")
        for line in lines:
            if ":" in line:
                n, d = line.split(":", 1)
                s["chars"].append({"name": n.strip(), "desc": d.strip()})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Karakter diimpor!", reply_markup=await menu_utama(uid))
        return

    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"desc_utama": text, "step": None})
        else: s["chars"][idx]["desc"] = text; await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"}); await update.message.reply_text(f"Deskripsi {text}?"); return
    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None}); await update.message.reply_text("Simpan!", reply_markup=await menu_utama(uid)); return

    # PROSES AI GENERATE
    if s["step"] in ["action", "narator_input"]:
        is_nar = (s["step"] == "narator_input")
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx].get("desc", "NPC")
        
        # STORY BIBLE: Plot + Kondisi dipaksa masuk ke System Prompt
        system = (f"Kamu RPG Engine. Perankan {tag} ({desc}).\n"
                  f"PLOT UTAMA: {s['plot']}\n"
                  f"KONDISI FISIK/LOKASI: {s['kondisi']}\n"
                  f"Tetap konsisten dengan Plot dan Kondisi di atas.")
        
        prompt = f"POV {tag}: {text}" if not is_nar else f"KEJADIAN: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        
        out, model = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ Server Sibuk.", reply_markup=await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, s = q.from_user.id, await get_state(q.from_user.id)
    await q.answer()

    if q.data == "menu_story":
        kb = [[InlineKeyboardButton("📝 Edit Plot/Sinopsis", callback_data="set_plot")],
              [InlineKeyboardButton("📍 Update Kondisi/Lokasi", callback_data="set_kondisi")],
              [InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")]]
        await q.edit_message_text(f"📖 *STORY BIBLE*\n\n*Plot:* {s['plot']}\n\n*Kondisi:* {s['kondisi']}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "set_plot":
        await save(uid, {"step": "set_plot"})
        await q.message.reply_text("Tuliskan Sinopsis atau Plot cerita agar AI tetap konsisten pada alur utama:")

    elif q.data == "set_kondisi":
        await save(uid, {"step": "updating_kondisi"})
        await q.message.reply_text("Update Kondisi (Busana/Lokasi) saat ini:")

    elif q.data == "load_prompt":
        await save(uid, {"step": "waiting_file"})
        await q.message.reply_text("Silakan kirimkan file .txt hasil ekspor cerita sebelumnya ke sini.")

    elif q.data == "export_logs":
        full_story = f"RIWAYAT: {s['name']}\n\n" + "\n\n".join(s["history"])
        file_data = io.BytesIO(full_story.encode()); file_data.name = f"Log_{s['name']}.txt"
        await q.message.reply_document(document=file_data, caption="📜 Riwayat.")

    # ... (Callback lainnya: list_all, sel_, act_, undo, regen, lanjut, reset tetap sama) ...
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ NPC", callback_data="add_new"), InlineKeyboardButton("📥 Import", callback_data="import_menu")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Karakter:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data == "import_menu": await save(uid, {"step": "import_chars"}); await q.message.reply_text("Format: Nama: Deskripsi")
    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); n = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton(f"💬 POV: {n}", callback_data=f"act_{idx}")], [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")], [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {n}", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Aksi {s['name'] if idx == -1 else s['chars'][idx]['name']}:")
    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": f"updating_{idx}"}); await q.message.reply_text("Deskripsi baru?")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Kejadian?")
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Dihapus.", reply_markup=await menu_utama(uid))
    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop(); out, m = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0].replace("POV ", "")
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, tag, await menu_utama(uid))
    elif q.data == "lanjut":
        out, m = await generate("Lanjutkan alur.", "Kamu Narator.", s["history"])
        if out: s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))
    elif q.data == "main_menu": await q.edit_message_text("Menu:", reply_markup=await menu_utama(uid))
    elif q.data == "add_new": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")
    elif q.data == "reset_confirm": await save(uid, {"history": [], "step": None, "chars": []}); await q.message.reply_text("🧹 Reset!")

# PENTING: Menambahkan handler untuk Document/File
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    # Handler pesan teks
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    # Handler khusus untuk upload file .txt
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), msg))
    print("V2.3 Story Bible & Load System Active...")
    app.run_polling()
