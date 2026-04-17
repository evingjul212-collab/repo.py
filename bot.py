import os
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient

# Abaikan peringatan library lama
warnings.filterwarnings("ignore", category=FutureWarning)

# Setup Koneksi
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Anda bisa ganti ke 'gemini-2.0-flash-exp' jika ingin model lebih cerdas
model = genai.GenerativeModel('gemini-2.5-flash') 

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
users = client.game_db.user_states

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id})
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("3. Save", callback_data='save'), InlineKeyboardButton("4. Load", callback_data='load')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')],
        [InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    if state and "name" in state:
        keyboard.insert(0, [InlineKeyboardButton(f"👤 Tokoh: {state['name']}", callback_data='aksi_user')])
    if state and "chars" in state:
        for char in state["chars"]:
            keyboard.append([InlineKeyboardButton(f"💬 Interaksi {char['name']}", callback_data=f"interaksi_{char['name']}")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Siapa nama tokoh utama Anda?")
    context.user_data['step'] = 'input_name'

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    step = context.user_data.get('step')

    if step == 'input_name':
        await users.update_one({"_id": uid}, {"$set": {"name": update.message.text, "history": [], "chars": []}}, upsert=True)
        context.user_data['step'] = 'input_aksi_user'
        await update.message.reply_text("Nama disimpan! Masukkan aksi awal tokoh utama:", reply_markup=await get_menu(uid))
    
    elif step == 'input_narator':
        res = model.generate_content(f"Tulis cerita rom-com 2 paragraf: {update.message.text}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        context.user_data['step'] = None
        await update.message.reply_text(f"📖 {res}", reply_markup=await get_menu(uid))

    elif step == 'wait_char_desc':
        name = context.user_data['temp_name']
        await users.update_one({"_id": uid}, {"$push": {"chars": {"name": name, "desc": update.message.text}}})
        context.user_data['step'] = None
        await update.message.reply_text(f"Karakter {name} ditambahkan!", reply_markup=await get_menu(uid))

    elif step == 'input_aksi_user':
        state = await users.find_one({"_id": uid})
        hist = state['history'][-1] if state.get('history') else "Awal cerita."
        res = model.generate_content(f"Tokoh {state['name']} melakukan: {update.message.text}. Lanjutkan cerita rom-com 2 paragraf. Histori: {hist}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        context.user_data['step'] = None
        await update.message.reply_text(f"✨ {res}", reply_markup=await get_menu(uid))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    
    if query.data == 'narator':
        context.user_data['step'] = 'input_narator'
        await query.edit_message_text("Masukkan alur cerita untuk narator:")
    elif query.data == 'tambah_karakter':
        context.user_data['step'] = 'wait_char_name'
        await query.edit_message_text("Masukkan nama karakter baru:")
    elif query.data == 'wait_char_name':
        context.user_data['temp_name'] = update.message.text # Tambahkan logic ini jika perlu
    elif query.data == 'aksi_user':
        context.user_data['step'] = 'input_aksi_user'
        await query.edit_message_text("Apa aksi tokoh utama sekarang?")
    elif query.data.startswith("interaksi_"):
        char_name = query.data.split("_")[1]
        state = await users.find_one({"_id": uid})
        char = next((c for c in state['chars'] if c['name'] == char_name), {"desc": "Teman"})
        res = model.generate_content(f"Interaksi 2 paragraf {state['name']} dan {char_name} ({char['desc']}). Cerita: {state['history'][-1]}").text
        await query.edit_message_text(f"💕 {res}", reply_markup=await get_menu(uid))

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.run_polling()
