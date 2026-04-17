import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient

# Setup
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
users = db = client.game_db.user_states

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id})
    # Tombol Dasar
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("3. Save", callback_data='save'), InlineKeyboardButton("4. Load", callback_data='load')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')],
        [InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    # Tambahkan tombol karakter sebagai opsi interaksi
    if state and "chars" in state:
        for char in state["chars"]:
            keyboard.append([InlineKeyboardButton(f"💬 Interaksi dengan {char}", callback_data=f"interaksi_{char}")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Siapa nama tokoh utama Anda?")
    context.user_data['wait_name'] = True

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get('wait_name'):
        await users.update_one({"_id": user_id}, {"$set": {"name": update.message.text, "history": [], "chars": []}}, upsert=True)
        context.user_data['wait_name'] = False
        await update.message.reply_text(f"Halo {update.message.text}, selamat datang!", reply_markup=await get_menu(user_id))
    elif context.user_data.get('wait_narator'):
        prompt = f"Tulis narasi pembuka rom-com berdasarkan alur ini: {update.message.text}"
        res = model.generate_content(prompt).text
        await users.update_one({"_id": user_id}, {"$push": {"history": res}})
        context.user_data['wait_narator'] = False
        await update.message.reply_text(f"📖 {res}", reply_markup=await get_menu(user_id))
    elif context.user_data.get('wait_char'):
        await users.update_one({"_id": user_id}, {"$push": {"chars": update.message.text}})
        context.user_data['wait_char'] = False
        await update.message.reply_text("Karakter ditambah!", reply_markup=await get_menu(user_id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    
    if query.data == 'narator':
        context.user_data['wait_narator'] = True
        await query.edit_message_text("Masukkan alur cerita yang kamu inginkan:")
    elif query.data == 'lanjut':
        state = await users.find_one({"_id": uid})
        res = model.generate_content(f"Lanjutkan cerita rom-com untuk {state['name']}: {state['history'][-1]}").text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        await query.edit_message_text(f"✨ {res}", reply_markup=await get_menu(uid))
    elif query.data == 'tambah_karakter':
        context.user_data['wait_char'] = True
        await query.edit_message_text("Masukkan nama karakter baru:")
    elif query.data.startswith("interaksi_"):
        char_name = query.data.split("_")[1]
        state = await users.find_one({"_id": uid})
        res = model.generate_content(f"Buat interaksi romantis antara {state['name']} dan {char_name}. Cerita: {state['history'][-1]}").text
        await query.edit_message_text(f"💕 {res}", reply_markup=await get_menu(uid))

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.run_polling()
