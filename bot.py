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
    context = "\n---\n".join(history[-30:]) if history else "Start."
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
        [InlineKeyboardButton("📜 Daftar Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut Alur", callback_data="lanjut")],
        [InlineKeyboardButton("📖 Baca Riwayat", callback_data="export_logs")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("🧹 Reset Total", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(update, text, tag, markup):
    try:
        await update.message.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await update.message.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine V2.1\nNama Tokoh Utama?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}!", reply_markup=await menu_utama(uid))
        return

    # FITUR BARU: Proses Import Massal
    if s["step"] == "import_chars":
        lines = text.split("\n")
        added = 0
        for line in lines:
            if ":" in line:
                c_name, c_desc = line.split(":", 1)
                s["chars"].append({"name": c_name.strip(), "desc": c_desc.strip()})
                added += 1
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"✅ Berhasil mengimpor {added} karakter!", reply_markup=await menu_utama(uid))
        return

    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"desc_utama": text, "step": None})
        else:
            s["chars"][idx]["desc"] = text
            await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi {text}?")
        return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"NPC {s['temp_char']} disimpan.", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action", "narator_input"]:
        is_nar = (s["step"] == "narator_input")
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx].get("desc", "NPC")
        system = f"Kamu RPG Engine. Perankan {tag} ({desc})."
        prompt = f"POV {tag}: {text}" if not is_nar else f"KEJADIAN: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, model = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ AI Sibuk.", reply_markup=await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, s = q.from_user.id, await get_state(q.from_user.id)
    await q.answer()

    if q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah Satu", callback_data="add_new"), InlineKeyboardButton("📥 Import Massal", callback_data="import_menu")])
        kb.append([InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Daftar Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "import_menu":
        await save(uid, {"step": "import_chars"})
        await q.message.reply_text("Kirimkan daftar karakter dengan format:\n\nNama: Deskripsi\nNama: Deskripsi\n\nContoh:\nRiko: Pendekar pedang sakti\nBudi: Pedagang pasar yang licik")

    elif q.data == "export_logs":
        full_story = f"RIWAYAT: {s['name']}\n" + ("="*20) + "\n\n" + "\n\n".join(s["history"])
        file_data = io.BytesIO(full_story.encode()); file_data.name = f"Log_{s['name']}.txt"
        await q.message.reply_document(document=file_data, caption="📜 Riwayat lengkap.")

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton(f"💬 POV: {name}", callback_data=f"act_{idx}")],
              [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Aksi {s['name'] if idx == -1 else s['chars'][idx]['name']}:")

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": f"updating_{idx}"})
        await q.message.reply_text("Deskripsi baru?")

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 Kejadian apa?")

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Dihapus.", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop()
        out, m = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0].replace("POV ", "")
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data == "lanjut":
        out, m = await generate("Lanjutkan alur.", "Kamu Narator.", s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "add_new": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")
    elif q.data == "reset_confirm": await save(uid, {"history": [], "step": None, "chars": []}); await q.message.reply_text("🧹 Reset!")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("V2.1 Import Feature Ready...")
    app.run_polling()
