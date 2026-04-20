import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Model sesuai daftar yang Bos punya
MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash"
]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= STATE LOGIC =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "Tanpa Nama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected"), # Index karakter yang sedang dipilih
        "temp_char": s.get("temp_char"),
        "last_prompt": s.get("last_prompt"),
        "story": s.get("story", {"setting": "Rumah", "time": "Sore"})
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
    context = "\n---\n".join(history[-8:]) if history else "Mulai cerita."
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[INSTRUKSI]\n{prompt}"
    
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return response.text.strip(), m
        except: continue
    return None, None

# ========= MENU BUILDERS =========
async def menu_utama(uid):
    s = await get_state(uid)
    kb = [
        [InlineKeyboardButton("📜 Daftar Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("🔄 Regen", callback_data="regen")]
    ]
    return InlineKeyboardMarkup(kb)

async def menu_karakter(idx, name):
    kb = [
        [InlineKeyboardButton(f"💬 Lanjut sebagai {name}", callback_data=f"act_{idx}")],
        [InlineKeyboardButton(f"📝 Edit Deskripsi", callback_data=f"edit_{idx}")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
    ]
    return InlineKeyboardMarkup(kb)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine V1.3 Aktif.\nSiapa nama Tokoh Utama kamu?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Salam, {text}!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi untuk {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"Karakter {s['temp_char']} disimpan.", reply_markup=await menu_utama(uid))
        return

    # LOGIKA EDIT DESKRIPSI
    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: # Update Tokoh Utama
            await save(uid, {"name": text, "step": None})
        else: # Update NPC
            chars = s["chars"]
            chars[idx]["desc"] = text
            await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text("✅ Deskripsi diperbarui.", reply_markup=await menu_utama(uid))
        return

    # PROMPT GENERATION
    if s["step"] == "action":
        idx = s["selected"]
        char_name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        prompt = f"POV {char_name}: {text}"
        system = f"Kamu adalah asisten RPG. Fokus pada aksi {char_name}. Deskripsi karakter: {text if idx == -1 else s['chars'][idx]['desc']}"
        
        await save(uid, {"last_prompt": prompt})
        out, model = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"{char_name}: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"**{char_name}**\n\n{out}", parse_mode="Markdown", reply_markup=await menu_utama(uid))
        else:
            await update.message.reply_text("Gagal generate. Coba lagi nanti.")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]):
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah Karakter Baru", callback_data="add_new")])
        kb.append([InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Pilih Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.edit_message_text(f"Karakter: {name}\nApa yang ingin kamu lakukan?", reply_markup=await menu_karakter(idx, name))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Apa aksi yang dilakukan {name}?")

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": f"updating_{idx}"})
        await q.message.reply_text("Silakan tulis deskripsi baru untuk karakter ini:")

    elif q.data == "add_new":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter baru?")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("Bot Berjalan...")
    app.run_polling()
    
