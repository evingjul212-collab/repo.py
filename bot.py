import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai
from motor.motor_asyncio import AsyncIOMotorClient

# Setup Gemini 2.0 Flash
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
response = client_gemini.models.generate_content(
    model="gemini-2.5-flash", # Sesuaikan dengan model yang Anda pakai
    contents=prompt
)
res = response.text
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

async def get_menu(user_id):
    state = await users.find_one({"_id": user_id})
    # Tombol utama
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("3. Save", callback_data='save'), InlineKeyboardButton("4. Load", callback_data='load')],
        [InlineKeyboardButton("5. Reset", callback_data='reset'), InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter')],
        [InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    # Tombol Tokoh Utama (User)
    if state and "name" in state:
        keyboard.insert(0, [InlineKeyboardButton(f"👤 Tokoh Utama: {state['name']}", callback_data='aksi_user')])
    
    # Tambahkan tombol karakter sebagai opsi interaksi
    if state and "chars" in state:
        for char in state["chars"]:
            keyboard.append([InlineKeyboardButton(f"💬 Interaksi dengan {char['name']}", callback_data=f"interaksi_{char['name']}")])
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Siapa nama tokoh utama Anda?")
    context.user_data['step'] = 'input_name'

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    step = context.user_data.get('step')

    if step == 'input_name':
        await users.update_one({"_id": uid}, {"$set": {"name": update.message.text, "history": [], "chars": []}}, upsert=True)
        context.user_data['step'] = 'input_aksi_user'
        await update.message.reply_text("Nama disimpan! Masukkan aksi/tindakan awal tokoh utama:", reply_markup=await get_menu(uid))
    
    elif step == 'input_narator':
        prompt = f"Tulis cerita rom-com 2 paragraf berdasarkan alur ini: {update.message.text}"
        res = model.generate_content(prompt).text
        await users.update_one({"_id": uid}, {"$push": {"history": res}})
        context.user_data['step'] = None
        await update.message.reply_text(f"📖 {res}", reply_markup=await get_menu(uid))

    elif step == 'input_char_desc':
        name = context.user_data['temp_char_name']
        desc = update.message.text
        await users.update_one({"_id": uid}, {"$push": {"chars": {"name": name, "desc": desc}}})
        context.user_data['step'] = None
        await update.message.reply_text(f"Karakter {name} ditambahkan!", reply_markup=await get_menu(uid))

    elif step == 'input_aksi_user':
        res = model.generate_content(f"Tokoh utama {update.message.text}. Lanjutkan cerita rom-com ini dalam 2 paragraf.").text
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
        await query.edit_message_text("Masukkan nama karakter baru:")
        context.user_data['step'] = 'wait_char_name'
    elif query.data == 'aksi_user':
        context.user_data['step'] = 'input_aksi_user'
        await query.edit_message_text("Masukkan aksi/tindakan tokoh utama:")
    elif query.data.startswith("interaksi_"):
        char_name = query.data.split("_")[1]
        state = await users.find_one({"_id": uid})
        char_data = next((c for c in state['chars'] if c['name'] == char_name), {})
        prompt = f"Buat interaksi romantis 2 paragraf antara {state['name']} dan {char_name} ({char_data['desc']}). Cerita sebelumnya: {state['history'][-1]}"
        res = model.generate_content(prompt).text
        await query.edit_message_text(f"💕 {res}", reply_markup=await get_menu(uid))
    elif query.data == 'wait_char_name': # Handling untuk input nama char
        context.user_data['temp_char_name'] = update.callback_query.message.text # logic bypass
        # (Sederhanakan alur di sini)
        
app = Application.builder().token(BOT_TOKEN).build()
# ... (tambahkan handler dan jalankan)
