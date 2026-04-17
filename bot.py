import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_stories = {}

@bot.message_handler(commands=['start'])
def start(message):
    """Memulai bot dan meminta nama karakter"""
    bot.send_message(message.chat.id, "✨ Romkom V3.1 ✨\nMasukkan nama karakter utama:")
    user_stories[message.chat.id] = {'character': None, 'actions': []}

@bot.message_handler(func=lambda m: True)
def handle_interaction(message):
    chat_id = message.chat.id
    
    if not user_stories[chat_id]['character']:
        # Set nama karakter pertama kali
        user_stories[chat_id]['character'] = message.text
        show_main_menu(chat_id, f"🎭 Karakter '{message.text}' telah dibuat!")
        bot.send_message(chat_id, f"Ketik /aksi untuk memulai petualangan {message.text}")
    elif message.text == '2. Lanjutkan':
        bot.send_message(chat_id, f"{user_stories[chat_id]['character']} sedang menunggu perintah...\nKetik /aksi [deskripsi]")

def show_main_menu(chat_id, text):
    """Menampilkan menu utama tanpa tombol karakter"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    bot.send_message(chat_id, text, reply_markup=markup)

bot.polling()
