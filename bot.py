import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    """Reset atau mulai baru"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "✨ Romkom V3.3 ✨\nMasukkan nama karakter utama:")
    user_data[chat_id] = {'character': None}

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    
    if not user_data.get(chat_id) or not user_data[chat_id]['character']:
        # Tahap input karakter
        user_data[chat_id] = {'character': message.text}
        show_character_prompt(chat_id)
        show_main_menu(chat_id)
    elif message.text == f"✨ {user_data[chat_id]['character']} ✨":
        # Tombol karakter dipilih
        ask_for_action(chat_id)
    elif message.text == '5. Reset':
        start(message)  # Reset ke awal

def show_character_prompt(chat_id):
    """Tampilkan tombol karakter terpisah"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"✨ {user_data[chat_id]['character']} ✨")
    bot.send_message(chat_id, "Pilih tombol karakter di atas untuk melanjutkan:", reply_markup=markup)

def show_main_menu(chat_id):
    """Tampilkan menu utama"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    bot.send_message(chat_id, "Menu:", reply_markup=markup)

def ask_for_action(chat_id):
    """Minta input aksi setelah karakter dipilih"""
    bot.send_message(chat_id, 
        f"📢 {user_data[chat_id]['character']} siap bertindak!\n"
        "Tulis aksi yang ingin dilakukan (contoh: 'menyelamatkan putri')")

bot.polling()
