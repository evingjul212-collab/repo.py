import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient

# Menggunakan TELEGRAM_TOKEN sesuai yang ada di Railway Anda
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

# Koneksi ke MongoDB Railway
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

async def get_user_state(user_id):
    state = await users.find_one({"_id": user_id})
    if not state:
        state = {"_id": user_id, "history": [], "char": "Belum ada"}
        await users.insert_one(state)
    return state

def get_menu():
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjutkan", callback_data='lanjut')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("7. Undo", callback_data='undo')],
        [InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Game dimulai! Pilih menu:", reply_markup=get_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    
    if query.data == 'reset':
        await users.update_one({"_id": uid}, {"$set": {"history": [], "char": "Belum ada"}})
        await query.edit_message_text("Game di-reset.", reply_markup=get_menu())
    elif query.data == 'narator':
        res = model.generate_content("Tulis pembukaan cerita rom-com.").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        await query.edit_message_text(f"📖 {res}", reply_markup=get_menu())
    elif query.data == 'lanjut':
        state = await get_user_state(uid)
        last_hist = state['history'][-1] if state['history'] else "Mulai cerita baru."
        res = model.generate_content(f"Lanjutkan cerita ini: {last_hist}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        await query.edit_message_text(f"✨ {res}", reply_markup=get_menu())
    elif query.data == 'tambah_karakter':
        context.user_data['wait'] = True
        await query.edit_message_text("Ketik nama karakter:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('wait'):
        await users.update_one({"_id": update.effective_user.id}, {"$set": {"char": update.message.text}})
        context.user_data['wait'] = False
        await update.message.reply_text("Karakter disimpan!", reply_markup=get_menu())

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.run_polling()
