import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Romkom V3.1\nMasukkan nama karakter utama:")
    user_data[message.chat.id] = {'character': None}

@bot.message_handler(func=lambda m: True)
def handle_actions(message):
    chat_id = message.chat.id
    
    if not user_data[chat_id]['character']:
        # Simpan nama karakter pertama kali
        user_data[chat_id]['character'] = message.text
        show_menu(chat_id, f"Karakter '{message.text}' telah dibuat!")
    else:
        # Proses aksi berdasarkan menu
        if message.text == '1. Narator':
            bot.send_message(chat_id, f"{user_data[chat_id]['character']} sedang mendengarkan narator...")
        elif message.text == '2. Lanjutkan':
            bot.send_message(chat_id, f"Apa yang ingin {user_data[chat_id]['character']} lakukan selanjutnya?")
        elif message.text == '5. Reset':
            user_data[chat_id]['character'] = None
            start(message)

def show_menu(chat_id, text):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    bot.send_message(chat_id, text, reply_markup=markup)

bot.polling()
