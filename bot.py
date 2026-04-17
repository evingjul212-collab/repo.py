import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Setup
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key="GEMINI_API_KEY")
model = genai.GenerativeModel('gemini-2.5-flash')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Penyimpanan Data Game (In-memory)
user_data = {}

def get_menu():
    keyboard = [
        [InlineKeyboardButton("1. Narator", callback_data='narator'), InlineKeyboardButton("2. Lanjutkan", callback_data='lanjut')],
        [InlineKeyboardButton("3. Save", callback_data='save'), InlineKeyboardButton("4. Load", callback_data='load')],
        [InlineKeyboardButton("5. Reset", callback_data='reset')],
        [InlineKeyboardButton("6. Tambah Karakter", callback_data='tambah_karakter'), InlineKeyboardButton("7. Undo", callback_data='undo')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {"history": [], "char": "Belum ada", "saved_state": None}
    await update.message.reply_text("Selamat datang di Game Rom-Com! Pilih menu di bawah:", reply_markup=get_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == 'reset':
        user_data[user_id] = {"history": [], "char": "Belum ada"}
        await query.edit_message_text("Game telah di-reset.", reply_markup=get_menu())
    
    elif query.data == 'narator':
        prompt = "Berikan narasi pembuka untuk game Visual Novel rom-com singkat dan menarik."
        response = model.generate_content(prompt).text
        user_data[user_id]["history"].append(response)
        await query.edit_message_text(f"📖 *Narator:*\n{response}", reply_markup=get_menu(), parse_mode='Markdown')

    elif query.data == 'lanjut':
        history_text = "\n".join(user_data[user_id]["history"][-3:])
        prompt = f"Lanjutkan cerita Visual Novel rom-com berikut dengan pilihan aksi yang menarik bagi pemain: {history_text}"
        response = model.generate_content(prompt).text
        user_data[user_id]["history"].append(response)
        await query.edit_message_text(f"✨ *Cerita:*\n{response}", reply_markup=get_menu(), parse_mode='Markdown')

    elif query.data == 'undo':
        if len(user_data[user_id]["history"]) > 0:
            user_data[user_id]["history"].pop()
            await query.edit_message_text("Pesan terakhir dihapus. Tekan 'Lanjutkan' untuk mencoba alur lain.", reply_markup=get_menu())

    elif query.data == 'tambah_karakter':
        await query.edit_message_text("Ketik nama karakter yang ingin kamu tambahkan (Contoh: 'Siska, gadis kutu buku'):")
        context.user_data['waiting_for_char'] = True

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get('waiting_for_char'):
        char_name = update.message.text
        user_data[user_id]["char"] = char_name
        context.user_data['waiting_for_char'] = False
        await update.message.reply_text(f"Karakter {char_name} berhasil ditambahkan!", reply_markup=get_menu())

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

app.run_polling()
