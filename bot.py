import os
import warnings
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, Defaults
)
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient
from google.api_core.exceptions import ResourceExhausted

warnings.filterwarnings("ignore", category=FutureWarning)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-3-flash')

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ================= UTIL =================

def safe_text(res):
    try:
        return res.text if res.text else "⚠️ AI kosong."
    except:
        return "⚠️ Error AI."

def trim(text, limit=2000):
    return text[:limit]

async def generate_ai(prompt):
    try:
        await asyncio.sleep(1)
        res = model.generate_content(prompt)
        return trim(safe_text(res))
    except ResourceExhausted:
        return "⚠️ Limit AI tercapai."
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# ================= MEMORY =================

def ensure_memory(state):
    defaults = {
        "time": "pagi",
        "location": "rumah",
        "scene": "awal cerita",
        "outfit": "pakaian santai",
        "history": ["Cerita dimulai."],
        "chars": []
    }
    for k, v in defaults.items():
        if k not in state:
            state[k] = v
    return state

def build_memory(state):
    return (
        f"Waktu: {state['time']}\n"
        f"Lokasi: {state['location']}\n"
        f"Scene: {state['scene']}\n"
        f"Outfit: {state['outfit']}\n"
    )

def update_memory_fields(state, text):
    t = text.lower()

    if "malam" in t: state["time"] = "malam"
    elif "sore" in t: state["time"] = "sore"
    elif "siang" in t: state["time"] = "siang"

    if "sekolah" in t: state["location"] = "sekolah"
    elif "pantai" in t: state["location"] = "pantai"

    if "ganti baju" in t:
        state["outfit"] = "pakaian baru"

    return state

def get_context(state):
    history = state.get("history", [])
    return "\n".join(history[-3:])

# ================= PROMPT =================

def build_prompt(memory, hist, action):
    return f"""
{memory}

LANJUTKAN CERITA.

RULE:
- Maksimal 2 paragraf
- Fokus dialog (minimal 60%)
- Gunakan tanda kutip untuk dialog
- Jangan ubah waktu/lokasi/outfit
- Jangan loncat waktu

KONTEKS:
{hist}

AKSI:
{action}
"""

# ================= MENU =================

async def get_menu(uid):
    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    keyboard = [
        [InlineKeyboardButton("📖 Narator", callback_data='narator'),
         InlineKeyboardButton("➡️ Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("➕ Karakter", callback_data='tambah_karakter'),
         InlineKeyboardButton("🔄 Reset", callback_data='reset')],
        [InlineKeyboardButton("↩️ Undo", callback_data='undo')]
    ]

    if state.get("name"):
        keyboard.insert(0, [
            InlineKeyboardButton(f"👤 {state['name']}", callback_data='aksi_user')
        ])

    for i, c in enumerate(state.get("chars", [])):
        keyboard.append([
            InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"c_{i}")
        ])

    return InlineKeyboardMarkup(keyboard)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one({"_id": update.effective_user.id},
                           {"$set": {"step": "input_name"}}, upsert=True)
    await update.message.reply_text("Masukkan nama tokoh:")

# ================= MESSAGE =================

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = ensure_memory(await users.find_one({"_id": uid}) or {})
    step = state.get("step")

    if step == "input_name":
        await users.update_one({"_id": uid}, {"$set": {
            "name": text,
            "step": None,
            "history": ["Cerita dimulai."]
        }})
        await update.message.reply_text("Nama disimpan!", reply_markup=await get_menu(uid))
        return

    if step == "wait_char_name":
        await users.update_one({"_id": uid}, {"$set": {"temp_char": text, "step": "wait_char_desc"}})
        await update.message.reply_text("Deskripsi karakter:")
        return

    if step == "wait_char_desc":
        name = state.get("temp_char")
        await users.update_one({"_id": uid}, {
            "$push": {"chars": {"name": name, "desc": text}},
            "$set": {"step": None}
        })
        await update.message.reply_text("Karakter ditambah!", reply_markup=await get_menu(uid))
        return

    if step in ["input_aksi_user", "input_narator", "input_char_action"]:
        state = update_memory_fields(state, text)

        memory = build_memory(state)
        hist = get_context(state)

        if step == "input_char_action":
            idx = state.get("selected_char")
            char = state["chars"][idx]
            action = f"{state['name']} ke {char['name']}: {text}"
        else:
            action = text

        prompt = build_prompt(memory, hist, action)
        out = await generate_ai(prompt)

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {
            "history": history,
            "step": None,
            "selected_char": None,
            "time": state["time"],
            "location": state["location"],
            "scene": state["scene"],
            "outfit": state["outfit"]
        }})

        await update.message.reply_text(out, reply_markup=await get_menu(uid))

# ================= BUTTON =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    if data == "narator":
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.message.reply_text("Input cerita:")

    elif data == "aksi_user":
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.message.reply_text("Aksi tokoh:")

    elif data.startswith("c_"):
        idx = int(data.split("_")[1])
        await users.update_one({"_id": uid}, {"$set": {
            "step": "input_char_action",
            "selected_char": idx
        }})
        await query.message.reply_text("Aksi ke karakter:")

    elif data == "lanjut":
        memory = build_memory(state)
        hist = get_context(state)

        prompt = build_prompt(memory, hist, "lanjutkan")

        out = await generate_ai(prompt)

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {"history": history}})

        await query.message.reply_text(out, reply_markup=await get_menu(uid))

    elif data == "undo":
        history = state.get("history", [])

        if len(history) > 1:
            history = history[:-1]

            await users.update_one({"_id": uid}, {"$set": {"history": history}})

            await query.message.reply_text(
                history[-1],
                reply_markup=await get_menu(uid)
            )
        else:
            await query.message.reply_text("Tidak bisa undo.")

    elif data == "tambah_karakter":
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.message.reply_text("Nama karakter:")

    elif data == "reset":
        await users.delete_one({"_id": uid})
        await query.message.reply_text("Reset selesai. /start lagi")

# ================= RUN =================

defaults = Defaults(parse_mode=None)

app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()
