import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "✨ Romkom V3.4 ✨\nMasukkan nama karakter utama:")
    user_data[chat_id] = {'character': None}

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    
    if not user_data.get(chat_id) or not user_data[chat_id]['character']:
        user_data[chat_id]['character'] = message.text
        # Gabungkan tombol karakter dan menu dalam 1 markup
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row(f"🎭 {user_data[chat_id]['character']} 🎭")
        markup.row('1. Narator', '2. Lanjutkan')
        markup.row('3. Save', '4. Load', '5. Reset')
        bot.send_message(chat_id, 
            f"Karakter {user_data[chat_id]['character']} siap!\n"
            "Pilih tombol karakter untuk melanjutkan", 
            reply_markup=markup)
    elif message.text == f"🎭 {user_data[chat_id]['character']} 🎭":
        ask_for_action(chat_id)
    elif message.text == '5. Reset':
        start(message)

def ask_for_action(chat_id):
    bot.send_message(chat_id,
        f"🛠️ Tulis aksi untuk {user_data[chat_id]['character']}:\n"
        "Contoh: 'berlari ke hutan', 'menyelamatkan kucing'")

bot.polling()
