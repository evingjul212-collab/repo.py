mport os
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup

def start(update, context):
    update.message.reply_text("Romkom V3.1")
    update.message.reply_text("Halo! Siapa nama Anda?")
    
def handle_name(update, context):
    user_name = update.message.text
    menu_buttons = [['1. Narator'], ['2. Lanjutkan'], ['3. Save'], ['4. Load']]
    reply_markup = ReplyKeyboardMarkup(menu_buttons, resize_keyboard=True)
    update.message.reply_text(f"Selamat datang {user_name}!", reply_markup=reply_markup)

TOKEN = os.environ['TELEGRAM_TOKEN']
updater = Updater(TOKEN, use_context=True)

# Handler tanpa karakter \ yang bermasalah
updater.dispatcher.add_handler(CommandHandler('start', start))
updater.dispatcher.add_handler(MessageHandler(Filters.text & \~Filters.command, handle_name))

updater.start_polling()
updater.idle()
