import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Romkom V3.1")
    bot.send_message(message.chat.id, "Halo! Siapa nama Anda?")

@bot.message_handler(func=lambda message: True)
def handle_name(message):
    user_name = message.text
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('1. Narator', '2. Lanjutkan', '3. Save', '4. Load')
    bot.send_message(message.chat.id, f"Selamat datang {user_name}!", reply_markup=markup)

bot.polling()
