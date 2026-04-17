import os
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, Defaults
)
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient

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

    # tombol karakter
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

    # ===== NARATOR =====
    elif step == "input_narator":
        try:
            res = model.generate_content(
                f"Tulis cerita romcom 2 paragraf:\n{text}"
            )
            out = trim(safe_text(res))

            await users.update_one(
                {"_id": uid},
                {"$push": {"history": out}, "$set": {"step": None}}
            )

            await update.message.reply_text(
                f"📖 {out}",
                reply_markup=await get_menu(uid)
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    # ===== AKSI USER =====
    elif step == "input_aksi_user":
        try:
            hist = state.get("history", ["Cerita dimulai."])[-1]

            res = model.generate_content(
                f"{state.get('name','Tokoh')} melakukan: {text}\n"
                f"Lanjutkan cerita romcom 2 paragraf.\n"
                f"Histori: {hist}"
            )

            out = trim(safe_text(res))

            await users.update_one(
                {"_id": uid},
                {"$push": {"history": out}, "$set": {"step": None}}
            )

            await update.message.reply_text(
                f"✨ {out}",
                reply_markup=await get_menu(uid)
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

# ================= BUTTON =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data

    await query.answer()

    state = await users.find_one({"_id": uid}) or {}

    # ===== NARATOR =====
    if data == 'narator':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.message.reply_text("Masukkan cerita:")

    # ===== TAMBAH KARAKTER =====
    elif data == 'tambah_karakter':
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.message.reply_text("Nama karakter:")

    # ===== AKSI USER =====
    elif data == 'aksi_user':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.message.reply_text("Aksi tokoh:")

    # ===== INTERAKSI KARAKTER (FIX UTAMA) =====
    elif data.startswith("c_"):
        try:
            idx = int(data.split("_")[1])
            chars = state.get("chars", [])

            if not chars:
                await query.message.reply_text("⚠️ Belum ada karakter.")
                return

            if idx >= len(chars):
                await query.message.reply_text("⚠️ Karakter tidak valid.")
                return

            char = chars[idx]
            hist = state.get("history", ["Cerita dimulai."])[-1]

            res = model.generate_content(
                f"Interaksi romantis-komedi 2 paragraf antara "
                f"{state.get('name','Tokoh')} dan {char['name']}.\n"
                f"Deskripsi: {char['desc']}\n"
                f"Histori: {hist}"
            )

            out = trim(safe_text(res))

            await users.update_one(
                {"_id": uid},
                {"$push": {"history": out}}
            )

            await query.message.reply_text(
                f"💕 {out}",
                reply_markup=await get_menu(uid)
            )

        except Exception as e:
            await query.message.reply_text(f"❌ Error interaksi: {e}")

    # ===== LANJUT =====
    elif data == 'lanjut':
        try:
            hist = state.get("history", ["Cerita dimulai."])[-1]

            res = model.generate_content(
                f"Lanjutkan cerita romcom 2 paragraf:\n{hist}"
            )

            out = trim(safe_text(res))

            await users.update_one(
                {"_id": uid},
                {"$push": {"history": out}}
            )

            await query.message.reply_text(
                f"✨ {out}",
                reply_markup=await get_menu(uid)
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")

    # ===== UNDO =====
    elif data == 'undo':
        hist = state.get("history", [])

        if len(hist) > 1:
            hist.pop()
            await users.update_one({"_id": uid}, {"$set": {"history": hist}})
            await query.message.reply_text("↩️ Undo berhasil.")
        else:
            await query.message.reply_text("⚠️ Tidak bisa undo.")

        await query.message.reply_text(reply_markup=await get_menu(uid))

    # ===== RESET =====
    elif data == 'reset':
        await users.delete_one({"_id": uid})
        await query.message.reply_text("🔄 Reset selesai. /start lagi")

# ================= RUN =================

defaults = Defaults(parse_mode='Markdown')

app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()
