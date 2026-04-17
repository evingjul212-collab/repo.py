import os
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from motor.motor_asyncio import AsyncIOMotorClient
from google.api_core import exceptions

warnings.filterwarnings("ignore", category=FutureWarning)

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# KONSISTEN: Menggunakan model 2.5 sesuai instruksi Anda
model = genai.GenerativeModel('gemini-2.5-flash') 

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
users = client.game_db.user_states

# Fungsi pembantu untuk memanggil AI dengan proteksi limit
async def generate_with_retry(prompt):
    try:
        response = model.generate_content(prompt)
        return response.text
    except exceptions.ResourceExhausted:
        return "⚠️ Kuota AI sedang penuh (Limit terlampaui). Tunggu sebentar lagi ya!"
    except Exception as e:
        return f"⚠️ Terjadi error: {str(e)}"

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id})
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("3. Save", callback_data='save'), InlineKeyboardButton("4. Load", callback_data='load')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')],
        [InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    if state and state.get("name"):
        keyboard.insert(0, [InlineKeyboardButton(f"👤 Tokoh: {state['name']}", callback_data='aksi_user')])
    if state and "chars" in state:
        for char in state["chars"]:
            keyboard.append([InlineKeyboardButton(f"💬 Interaksi {char['name']}", callback_data=f"int_{char['name']}")])
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
        await users.update_one({"_id": uid}, {"$set": {"temp_char_name": text, "step": "wait_char_desc"}})
        await update.message.reply_text(f"Nama '{text}' disimpan. Masukkan deskripsi & hubungan dengan tokoh utama:")

    elif step == "wait_char_desc":
        name = state.get("temp_char_name")
        await users.update_one({"_id": uid}, {"$push": {"chars": {"name": name, "desc": text}}, "$set": {"step": None}})
        await update.message.reply_text(f"Karakter {name} ditambahkan!", reply_markup=await get_menu(uid))

    elif step == "input_narator":
        res = await generate_with_retry(f"Tulis 2 paragraf cerita rom-com: {text}")
        await users.update_one({"_id": uid}, {"$push": {"history": res}, "$set": {"step": None}})
        await update.message.reply_text(f"📖 {res}", reply_markup=await get_menu(uid))

    elif step == "input_aksi_user":
        hist = state['history'][-1] if state.get('history') else "Cerita dimulai."
        res = await generate_with_retry(f"Tokoh {state['name']} melakukan: {text}. Lanjutkan cerita rom-com 2 paragraf. Histori: {hist}")
        await users.update_one({"_id": uid}, {"$push": {"history": res}, "$set": {"step": None}})
        await update.message.reply_text(f"✨ {res}", reply_markup=await get_menu(uid))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()
    
    if data == 'narator':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.edit_message_text("Masukkan alur cerita untuk narator:")
    elif data == 'tambah_karakter':
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.edit_message_text("Masukkan nama karakter baru:")
    elif data == 'aksi_user':
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.edit_message_text("Apa aksi tokoh utama sekarang?")
    elif data.startswith("int_"):
        char_name = data.split("_")[1]
        state = await users.find_one({"_id": uid})
        char = next((c for c in state.get('chars', []) if c['name'] == char_name), {"desc": "Teman dekat"})
        hist = state.get('history', [])
        last_hist = hist[-1] if hist else "Cerita baru saja dimulai."
        res = await generate_with_retry(f"Buat interaksi 2 paragraf antara {state['name']} dan {char_name}. Deskripsi: {char['desc']}. Histori: {last_hist}")
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        await query.edit_message_text(f"💕 {res}", reply_markup=await get_menu(uid))
    elif data == 'reset':
        await users.delete_one({"_id": uid})
        await query.edit_message_text("Data dihapus. Ketik /start untuk mulai lagi.")
    elif data == 'undo':
        await users.update_one({"_id": uid}, {"$pop": {"history": 1}})
        await query.edit_message_text("Pesan terakhir dihapus.", reply_markup=await get_menu(uid))

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
app.run_polling()
