import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "✨ Romkom V3.2 ✨\nMasukkan nama karakter utama:")
    user_data[message.chat.id] = {'character': None}

@bot.message_handler(func=lambda m: True)
def handle_actions(message):
    chat_id = message.chat.id
    
    if not user_data[chat_id]['character']:
        user_data[chat_id]['character'] = message.text
        show_character_button(chat_id, message.text)
    elif message.text == f"Pilih {user_data[chat_id]['character']}":
        ask_for_action(chat_id)

def show_character_button(chat_id, character_name):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"Pilih {character_name}")  # Tombol khusus pilih karakter
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load')
    bot.send_message(chat_id, f"Karakter '{character_name}' siap!", reply_markup=markup)

def ask_for_action(chat_id):
    character = user_data[chat_id]['character']
    bot.send_message(chat_id, f"📝 Tulis aksi untuk {character}:\n(Contoh: 'pergi ke hutan', 'memanggil teman')")

bot.polling()
