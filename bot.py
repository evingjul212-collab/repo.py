import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])

user_stories = {}  # Menyimpan cerita per user

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Romkom V3.1\nHalo! Masukkan nama karakter utama:")

@bot.message_handler(func=lambda m: True)
def handle_actions(message):
    chat_id = message.chat.id
    
    if chat_id not in user_stories:
        # Jika baru, simpan nama karakter
        user_stories[chat_id] = {'character': message.text}
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(message.text)  # Tombol dengan nama karakter
        bot.send_message(chat_id, f"Karakter '{message.text}' dibuat!\nPilih karakter untuk melanjutkan cerita:", reply_markup=markup)
    else:
        # Jika tombol karakter dipilih
        if message.text == user_stories[chat_id]['character']:
            bot.send_message(chat_id, f"Apa aksi {message.text} selanjutnya? (contoh: 'pergi ke hutan', 'bertemu penyihir')")

bot.polling()
