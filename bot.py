import os
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Defaults
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient

# Abaikan warning
warnings.filterwarnings("ignore", category=FutureWarning)

# Setup
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# KONSISTEN: Menggunakan model 2.5 flash
model = genai.GenerativeModel('gemini-2.5-flash') 

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id})
    if not state: return None
    
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')],
        [InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    if state.get("name"):
        keyboard.insert(0, [InlineKeyboardButton(f"👤 Tokoh: {state['name']}", callback_data='aksi_user')])
    
    if "chars" in state:
        for i, char in enumerate(state["chars"]):
            keyboard.append([InlineKeyboardButton(f"💬 Interaksi {char['name']}", callback_data=f"c_{i}")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one({"_id": update.effective_user.id}, {"$set": {"step": "input_name"}}, upsert=True)
    await update.message.reply_text("Halo! Siapa nama tokoh utama Anda?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = await users.find_one({"_id": uid})
    step = state.get("step") if state else None

    if step == "input_name":
        await users.update_one({"_id": uid}, {"$set": {"name": text, "history": ["Cerita dimulai."], "chars": [], "step": None}}, upsert=True)
        await update.message.reply_text(f"Nama {text} disimpan!", reply_markup=await get_menu(uid))
    
    elif step == "wait_char_name":
        await users.update_one({"_id": uid}, {"$set": {"temp_char": text, "step": "wait_char_desc"}})
        await update.message.reply_text(f"Nama '{text}' disimpan. Masukkan deskripsi & hubungan dengan tokoh utama:")

    elif step == "wait_char_desc":
        name = state.get("temp_char")
        await users.update_one({"_id": uid}, {"$push": {"chars": {"name": name, "desc": text}}, "$set": {"step": None, "temp_char": ""}})
        await update.message.reply_text(f"Karakter {name} berhasil ditambahkan!", reply_markup=await get_menu(uid))

    elif step == "input_narator":
        res = model.generate_content(f"Tulis 2 paragraf cerita rom-com: {text}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}, "$set": {"step": None}})
        await update.message.reply_text(f"📖 {res}", reply_markup=await get_menu(uid))

    elif step == "input_aksi_user":
        hist = state['history'][-1] if state.get('history') else "Cerita dimulai."
        res = model.generate_content(f"Tokoh {state['name']} melakukan: {text}. Lanjutkan cerita rom-com 2 paragraf. Histori: {hist}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}, "$set": {"step": None}})
        await update.message.reply_text(f"✨ {res}", reply_markup=await get_menu(uid))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()
    
    if data == 'narator':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.message.reply_text("Masukkan alur cerita untuk narator:")
    elif data == 'tambah_karakter':
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.message.reply_text("Masukkan nama karakter baru:")
    elif data == 'aksi_user':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.message.reply_text("Apa aksi tokoh utama sekarang?")
    elif data.startswith("c_"):
        idx = int(data.split("_")[1])
        state = await users.find_one({"_id": uid})
        char = state['chars'][idx]
        hist = state.get('history', ["Cerita dimulai."])
        res = model.generate_content(f"Buat interaksi 2 paragraf antara {state['name']} dan {char['name']}. Deskripsi: {char['desc']}. Histori: {hist[-1]}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        # Pakai reply_text agar tidak kena error "not modified"
        await query.message.reply_text(f"💕 {res}", reply_markup=await get_menu(uid))
    elif data == 'reset':
        await users.delete_one({"_id": uid})
        await query.message.reply_text("Data dihapus. Ketik /start untuk mulai lagi.")
    elif data == 'undo':
        await users.update_one({"_id": uid}, {"$pop": {"history": 1}})
        await query.message.reply_text("Pesan terakhir dihapus.", reply_markup=await get_menu(uid))
    elif data == 'lanjut':
        state = await users.find_one({"_id": uid})
        hist = state.get('history', ["Cerita dimulai."])
        res = model.generate_content(f"Lanjutkan cerita rom-com 2 paragraf: {hist[-1]}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        await query.message.reply_text(f"✨ {res}", reply_markup=await get_menu(uid))

# Gunakan defaults agar parse_mode otomatis Markdown
defaults = Defaults(parse_mode='Markdown')
app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

app.run_polling()
