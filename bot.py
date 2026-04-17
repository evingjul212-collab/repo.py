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
model = genai.GenerativeModel('gemini-2.5-flash')

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ================= UTIL =================

def safe_text(res):
    try:
        return res.text if res.text else "⚠️ AI tidak merespon."
    except:
        return "⚠️ Error dari AI."

def trim(text, limit=4000):
    return text[:limit]

async def generate_ai(prompt):
    try:
        await asyncio.sleep(1)
        res = model.generate_content(prompt)
        return trim(safe_text(res))
    except ResourceExhausted:
        return "⚠️ Limit AI tercapai (free quota). Coba lagi nanti."
    except Exception as e:
        return f"⚠️ Error AI: {str(e)}"

# ================= MEMORY SYSTEM =================

def build_memory(state):
    return (
        f"Waktu: {state.get('time')}\n"
        f"Lokasi: {state.get('location')}\n"
        f"Scene: {state.get('scene')}\n"
        f"Outfit: {state.get('outfit')}\n"
    )

def update_memory_fields(state, text):
    t = text.lower()

    # waktu
    if "malam" in t: state["time"] = "malam"
    elif "sore" in t: state["time"] = "sore"
    elif "siang" in t: state["time"] = "siang"
    elif "pagi" in t: state["time"] = "pagi"

    # lokasi
    if "sekolah" in t: state["location"] = "sekolah"
    elif "pantai" in t: state["location"] = "pantai"
    elif "rumah" in t: state["location"] = "rumah"
    elif "kafe" in t: state["location"] = "kafe"

    # outfit
    if "ganti baju" in t:
        state["outfit"] = "pakaian baru"

    # scene
    if "masuk" in t:
        state["scene"] = "di dalam ruangan"
    elif "keluar" in t:
        state["scene"] = "di luar"

    return state

# ================= MENU =================

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id}) or {}

    keyboard = [
        [
            InlineKeyboardButton("📖 Narator", callback_data='narator'),
            InlineKeyboardButton("➡️ Lanjut", callback_data='lanjut')
        ],
        [
            InlineKeyboardButton("➕ Karakter", callback_data='tambah_karakter'),
            InlineKeyboardButton("🔄 Reset", callback_data='reset')
        ],
        [
            InlineKeyboardButton("↩️ Undo", callback_data='undo')
        ]
    ]

    if state.get("name"):
        keyboard.insert(0, [
            InlineKeyboardButton(f"👤 {state['name']}", callback_data='aksi_user')
        ])

    for i, char in enumerate(state.get("chars", [])):
        keyboard.append([
            InlineKeyboardButton(f"💬 {char['name']}", callback_data=f"c_{i}")
        ])

    return InlineKeyboardMarkup(keyboard)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one(
        {"_id": update.effective_user.id},
        {"$set": {"step": "input_name"}},
        upsert=True
    )
    await update.message.reply_text("Masukkan nama tokoh utama:")

# ================= MESSAGE =================

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = await users.find_one({"_id": uid}) or {}
    step = state.get("step")

    # ===== INPUT NAMA =====
    if step == "input_name":
        await users.update_one(
            {"_id": uid},
            {"$set": {
                "name": text,
                "time": "pagi",
                "location": "rumah",
                "scene": "awal cerita",
                "outfit": "pakaian santai",
                "history": ["Cerita dimulai."],
                "chars": [],
                "step": None
            }},
            upsert=True
        )

        await update.message.reply_text(
            f"✅ Nama: {text}",
            reply_markup=await get_menu(uid)
        )

    # ===== TAMBAH KARAKTER =====
    elif step == "wait_char_name":
        await users.update_one(
            {"_id": uid},
            {"$set": {"temp_char": text, "step": "wait_char_desc"}}
        )
        await update.message.reply_text("Deskripsi & hubungan:")

    elif step == "wait_char_desc":
        name = state.get("temp_char", "TanpaNama")

        await users.update_one(
            {"_id": uid},
            {
                "$push": {"chars": {"name": name, "desc": text}},
                "$set": {"step": None, "temp_char": ""}
            }
        )

        await update.message.reply_text(
            f"✅ Karakter {name} ditambahkan!",
            reply_markup=await get_menu(uid)
        )

    # ===== AKSI USER / NARATOR / KARAKTER =====
    elif step in ["input_aksi_user", "input_narator", "input_char_action"]:
        state = update_memory_fields(state, text)

        await users.update_one(
            {"_id": uid},
            {"$set": {
                "time": state["time"],
                "location": state["location"],
                "scene": state["scene"],
                "outfit": state["outfit"]
            }}
        )

        hist = state.get("history", ["Cerita dimulai."])[-1]
        memory = build_memory(state)

        if step == "input_char_action":
            idx = state.get("selected_char")
            char = state.get("chars", [])[idx]

            prompt = (
                f"{memory}\n"
                f"{state['name']} melakukan: {text} kepada {char['name']}.\n"
                f"Deskripsi karakter: {char['desc']}\n"
                f"JANGAN ubah waktu/lokasi/outfit kecuali disebutkan.\n"
                f"Histori: {hist}"
            )
        else:
            prompt = (
                f"{memory}\n"
                f"{state['name']} melakukan: {text}\n"
                f"JANGAN ubah waktu/lokasi/outfit kecuali disebutkan.\n"
                f"Histori: {hist}"
            )

        out = await generate_ai(prompt)

        await users.update_one(
            {"_id": uid},
            {"$push": {"history": out}, "$set": {"step": None, "selected_char": None}}
        )

        await update.message.reply_text(
            f"✨ {out}",
            reply_markup=await get_menu(uid)
        )

# ================= BUTTON =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data

    await query.answer()
    state = await users.find_one({"_id": uid}) or {}

    if data == 'narator':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.message.reply_text("Masukkan cerita:")

    elif data == 'tambah_karakter':
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.message.reply_text("Nama karakter:")

    elif data == 'aksi_user':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.message.reply_text("Aksi tokoh:")

    elif data.startswith("c_"):
        idx = int(data.split("_")[1])
        await users.update_one(
            {"_id": uid},
            {"$set": {"step": "input_char_action", "selected_char": idx}}
        )
        await query.message.reply_text("Aksi ke karakter?")

    elif data == 'lanjut':
        hist = state.get("history", ["Cerita dimulai."])[-1]
        memory = build_memory(state)

        out = await generate_ai(
            f"{memory}\nLanjutkan cerita.\nHistori: {hist}"
        )

        await users.update_one(
            {"_id": uid},
            {"$push": {"history": out}}
        )

        await query.message.reply_text(
            f"✨ {out}",
            reply_markup=await get_menu(uid)
        )

    elif data == 'undo':
        hist = state.get("history", [])
        if len(hist) > 1:
            hist.pop()
            await users.update_one({"_id": uid}, {"$set": {"history": hist}})
            await query.message.reply_text(
                f"↩️ {hist[-1]}",
                reply_markup=await get_menu(uid)
            )
        else:
            await query.message.reply_text("⚠️ Tidak bisa undo.")

    elif data == 'reset':
        await users.delete_one({"_id": uid})
        await query.message.reply_text("🔄 Reset selesai. /start lagi")

# ================= RUN =================

defaults = Defaults(parse_mode=None)

app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()
