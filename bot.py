import os
import asyncio
import io
import re # Tambahan regex untuk deteksi lebih akurat
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
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"
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

async def safe_send(update, text, tag, markup):
    try:
        await update.message.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await update.message.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await get_state(uid)
    await update.message.reply_text("🎮 RPG Engine V2.6 [Fixed Parser]\nSiap beraksi?", reply_markup=await menu_utama(uid))

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    s = await get_state(uid)
    
    # --- LOGIKA LOAD FILE V2.6 (ULTRA FLEXIBLE) ---
    if update.message.document and s["step"] == "waiting_file":
        file = await update.message.document.get_file()
        byte_content = await file.download_as_bytearray()
        full_text = byte_content.decode("utf-8")
        
        # Pisahkan baris dengan regex agar kebal terhadap \n atau \r\n
        lines = re.split(r'\r?\n', full_text)
        
        new_history, new_chars = [], []
        f_plot, f_kondisi = s["plot"], s["kondisi"]

        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Deteksi Karakter (Case Insensitive)
            if line.upper().startswith("KARAKTER:"):
                try:
                    content = line.split(":", 1)[1].strip()
                    sep = "-" if "-" in content else ":"
                    if sep in content:
                        p = content.split(sep, 1)
                        new_chars.append({"name": p[0].strip(), "desc": p[1].strip()})
                except: continue
            
            # Deteksi Plot & Kondisi
            elif line.upper().startswith("PLOT:"):
                f_plot = line.split(":", 1)[1].strip()
            elif line.upper().startswith("KONDISI:"):
                f_kondisi = line.split(":", 1)[1].strip()
                
            # Deteksi Riwayat (Pola: [Nama]: atau [Nama]:)
            elif re.search(r'^\[.*\]\s*:', line):
                new_history.append(line)

        # Hanya update jika data ditemukan
        upd = {"step": None}
        if new_history: upd["history"] = new_history
        if new_chars: upd["chars"] = new_chars
        if f_plot: upd["plot"] = f_plot
        if f_kondisi: upd["kondisi"] = f_kondisi

        await save(uid, upd)
        await update.message.reply_text(
            f"✅ **Sinkronisasi Berhasil!**\n\n- {len(new_history)} Baris Cerita\n- {len(new_chars)} NPC Terbaca\n\n"
            f"AI kini sudah sinkron dengan file save.", 
            parse_mode="Markdown", reply_markup=await menu_utama(uid)
        )
        return

    # --- INPUT LOGIC ---
    if s["step"] == "set_plot":
        await save(uid, {"plot": text, "step": None}); await update.message.reply_text("✅ Plot ok.", reply_markup=await menu_utama(uid)); return
    if s["step"] == "updating_kondisi":
        await save(uid, {"kondisi": text, "step": None}); await update.message.reply_text("✅ Kondisi ok.", reply_markup=await menu_utama(uid)); return
    if s["step"] == "import_chars":
        for l in text.split("\n"):
            if ":" in l: n, d = l.split(":", 1); s["chars"].append({"name": n.strip(), "desc": d.strip()})
        await save(uid, {"chars": s["chars"], "step": None}); await update.message.reply_text("✅ Impor ok.", reply_markup=await menu_utama(uid)); return
    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"desc_utama": text, "step": None})
        else: s["chars"][idx]["desc"] = text; await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Ok.", reply_markup=await menu_utama(uid)); return
    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"}); await update.message.reply_text(f"Deskripsi {text}?"); return
    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None}); await update.message.reply_text("Ok!", reply_markup=await menu_utama(uid)); return

    # --- AI PROCESS ---
    if s["step"] in ["action", "narator_input"]:
        is_nar = (s["step"] == "narator_input")
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx].get("desc", "NPC")
        system = f"RPG Engine. Perankan {tag} ({desc}).\nPLOT: {s['plot']}\nKONDISI: {s['kondisi']}"
        prompt = f"POV {tag}: {text}" if not is_nar else f"KEJADIAN: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, m = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, s = q.from_user.id, await get_state(q.from_user.id)
    await q.answer()
    if q.data == "menu_story":
        kb = [[InlineKeyboardButton("📝 Plot", callback_data="set_plot"), InlineKeyboardButton("📍 Kondisi", callback_data="set_kondisi")], [InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]]
        await q.edit_message_text(f"📖 *STORY BIBLE*\n\n*Plot:* {s['plot']}\n*Kondisi:* {s['kondisi']}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data == "export_logs":
        meta = f"PLOT: {s['plot']}\nKONDISI: {s['kondisi']}\n"
        for c in s["chars"]: meta += f"KARAKTER: {c['name']} - {c['desc']}\n"
        full = f"--- RPG DATA ---\n{meta}\n--- RIWAYAT ---\n\n" + "\n\n".join(s["history"])
        f_data = io.BytesIO(full.encode()); f_data.name = f"RPG_Save_{s['name']}.txt"
        await q.message.reply_document(document=f_data, caption="📜 Simpan file ini.")
    elif q.data == "load_prompt": await save(uid, {"step": "waiting_file"}); await q.message.reply_text("Kirim file .txt.")
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ NPC", callback_data="add_new"), InlineKeyboardButton("📥 Import", callback_data="import_menu")],[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Karakter:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "set_plot": await save(uid, {"step": "set_plot"}); await q.message.reply_text("Tulis Plot:")
    elif q.data == "set_kondisi": await save(uid, {"step": "updating_kondisi"}); await q.message.reply_text("Tulis Kondisi:")
    elif q.data == "import_menu": await save(uid, {"step": "import_chars"}); await q.message.reply_text("Format Nama: Deskripsi")
    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); n = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton(f"💬 POV: {n}", callback_data=f"act_{idx}")], [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")], [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {n}", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx, "step": "action"}); await q.message.reply_text(f"Aksi {s['name'] if idx == -1 else s['chars'][idx]['name']}:")
    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": f"updating_{idx}"}); await q.message.reply_text("Deskripsi?")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Kejadian?")
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Ok.", reply_markup=await menu_utama(uid))
    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop(); out, m = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out: tag = s["last_prompt"].split(":")[0].replace("POV ", ""); s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))
    elif q.data == "lanjut":
        out, m = await generate("Lanjutkan alur.", "Kamu Narator.", s["history"])
        if out: s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))
    elif q.data == "reset_confirm": await save(uid, {"history": [], "step": None, "chars": []}); await q.message.reply_text("🧹 Reset!")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), msg))
    print("V2.6 Online...")
    app.run_polling()
