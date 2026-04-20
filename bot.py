import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro"
]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= DATABASE LOGIC =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "User",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama", # Field Baru khusus Deskripsi Utama
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "temp_char": s.get("temp_char"),
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
    context = "\n---\n".join(history[-10:]) if history else "Start."
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
    await update.message.reply_text("🎮 RPG Engine V1.8 [Bug Fixed]\nNama Tokoh Utama?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}!", reply_markup=await menu_utama(uid))
        return

    # BUG FIX: Memisahkan update Nama vs Deskripsi Tokoh Utama
    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: 
            await save(uid, {"desc_utama": text, "step": None}) # Simpan ke desc_utama, bukan name
        else:
            s["chars"][idx]["desc"] = text
            await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Identitas berhasil diperbarui.", reply_markup=await menu_utama(uid))
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

    # BUG FIX: Logika POV Karakter agar tidak nyasar ke Narator
    if s["step"] in ["action", "narator_input"]:
        is_nar = (s["step"] == "narator_input")
        idx = s.get("selected", -1)
        
        if is_nar:
            tag, desc = "NARASI", "Narator"
            prompt = f"KEJADIAN: {text}"
        else:
            # Jika idx -1 pakai data Utama, jika >= 0 pakai data NPC
            tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
            desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
            prompt = f"POV {tag}: {text}"
        
        system = f"Kamu RPG Engine. Perankan {tag} ({desc}). Respon imersif."
        await save(uid, {"last_prompt": prompt, "last_system": system})
        
        out, model = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"**{tag}**: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ Server Sibuk.", reply_markup=await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_new"), InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Daftar Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton(f"💬 POV: {name}", callback_data=f"act_{idx}")],
              [InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"edit_{idx}")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"selected": idx, "step": "action"})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.message.reply_text(f"Ketik aksi untuk {name}:")

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": f"updating_{idx}"})
        await q.message.reply_text("Tulis deskripsi baru (Ini tidak akan mengubah nama):")

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 [NARATOR] Apa yang terjadi?")
    
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Terakhir dihapus.", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt"): return
        if s["history"]: s["history"].pop()
        out, m = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0].replace("POV ", "")
            s["history"].append(f"**{tag}**: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data == "lanjut":
        out, m = await generate("Lanjutkan cerita.", "Kamu Narator.", s["history"])
        if out:
            s["history"].append(f"**NARASI**: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "add_new": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "reset_confirm": await save(uid, {"history": [], "step": None, "chars": []}); await q.message.reply_text("🧹 Reset!")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("V1.8 Fixed Deployment...")
    app.run_polling()
