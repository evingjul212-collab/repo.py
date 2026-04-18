import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ========= BASIC =========
def default_state():
    return {
        "name": None,
        "step": None,
        "history": [],
        "chars": [],
        "last_prompt": None
    }

async def get_state(uid):
    state = await users.find_one({"_id": uid})
    if not state:
        state = default_state()
        await users.insert_one({"_id": uid, **state})
    return state

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data})

# ========= AI =========
async def generate(prompt):
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            lambda: model.generate_content(prompt)
        )
        return res.text.strip()
    except:
        return None

# ========= MENU =========
async def menu(uid):
    state = await get_state(uid)

    kb = []

    if state["name"]:
        kb.append([InlineKeyboardButton(f"👤 {state['name']}", callback_data="main")])

    kb += [
        [InlineKeyboardButton("📖 Narator", callback_data="narator"),
         InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("➕ Karakter", callback_data="add_char"),
         InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ]

    for i, c in enumerate(state["chars"]):
        kb.append([InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")])

    return InlineKeyboardMarkup(kb)

def error_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Retry", callback_data="retry")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ])

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"step": "set_name"})
    await update.message.reply_text("Nama tokoh utama?")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = await get_state(uid)
    step = state["step"]

    # ===== SET NAME =====
    if step == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text("Nama disimpan!", reply_markup=await menu(uid))
        return

    # ===== TAMBAH KARAKTER =====
    if step == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text("Deskripsi karakter?")
        return

    if step == "char_desc":
        chars = state["chars"]
        chars.append({"name": state["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None, "temp_char": ""})
        await update.message.reply_text("Karakter ditambahkan!", reply_markup=await menu(uid))
        return

    # ===== AKSI TOKOH UTAMA =====
    if step == "main_action":
        prompt = f"{state['name']} melakukan: {text}. Lanjutkan cerita 2 paragraf."
    
    # ===== NARATOR =====
    elif step == "narator":
        prompt = f"Buat adegan dari ini: {text}. 2 paragraf."

    # ===== INTERAKSI KARAKTER =====
    elif step == "char_action":
        char = state["chars"][state["selected"]]
        prompt = f"Reaksi {char['name']} terhadap: {text}. 2 paragraf."

    else:
        return

    await save(uid, {"last_prompt": prompt})

    out = await generate(prompt)

    if not out:
        await update.message.reply_text("AI error", reply_markup=error_menu())
        return

    history = state["history"]
    history.append(out)

    await save(uid, {"history": history, "step": None})

    await update.message.reply_text(out, reply_markup=await menu(uid))

# ========= BUTTON =========
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    try:
        await q.answer()
    except:
        pass

    state = await get_state(uid)

    # ===== TOKOH UTAMA =====
    if data == "main":
        await save(uid, {"step": "main_action"})
        await q.message.reply_text("Aksi tokoh utama?")

    # ===== NARATOR =====
    elif data == "narator":
        await save(uid, {"step": "narator"})
        await q.message.reply_text("Masukkan cerita:")

    # ===== LANJUT =====
    elif data == "lanjut":
        if not state["history"]:
            await q.message.reply_text("Belum ada cerita.")
            return

        prompt = f"Lanjutkan: {state['history'][-1]}"
        out = await generate(prompt)

        if out:
            history = state["history"]
            history.append(out)
            await save(uid, {"history": history})
            await q.message.reply_text(out, reply_markup=await menu(uid))

    # ===== TAMBAH KARAKTER =====
    elif data == "add_char":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter?")

    # ===== INTERAKSI KARAKTER =====
    elif data.startswith("char_"):
        idx = int(data.split("_")[1])
        await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text("Aksi ke karakter ini?")

    # ===== UNDO =====
    elif data == "undo":
        history = state["history"]
        if len(history) > 1:
            history.pop()
            await save(uid, {"history": history})
            await q.message.reply_text(history[-1], reply_markup=await menu(uid))
        else:
            await q.message.reply_text("Tidak bisa undo.")

    # ===== RETRY =====
    elif data == "retry":
        prompt = state.get("last_prompt")
        if not prompt:
            await q.message.reply_text("Tidak ada data.")
            return

        out = await generate(prompt)

        if out:
            history = state["history"]
            history.append(out)
            await save(uid, {"history": history})
            await q.message.reply_text(out, reply_markup=await menu(uid))
        else:
            await q.message.reply_text("Masih error.")

# ========= RUN =========
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("BOT RUNNING...")
app.run_polling(drop_pending_updates=True)
