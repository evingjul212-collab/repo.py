import os
import telebot

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
user_stories = {}

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Romkom V3.1\nMasukkan nama karakter utama:")
    user_stories[message.chat.id] = {'character': None, 'actions': []}

@bot.message_handler(func=lambda m: True)
def handle_actions(message):
    chat_id = message.chat.id
    data = user_stories.get(chat_id, {})
    
    if not data.get('character'):
        # Simpan nama karakter pertama kali
        user_stories[chat_id]['character'] = message.text
        show_character_menu(chat_id, message.text)
    elif message.text == user_stories[chat_id]['character']:
        # Jika karakter dipilih
        bot.send_message(chat_id, f"{message.text} sedang berdiri di persimpangan jalan...\nApa yang akan {message.text} lakukan?")
    elif message.text.startswith('aksi:'):
        # Simpan aksi karakter
        action = message.text[5:].strip()
        user_stories[chat_id]['actions'].append(action)
        bot.send_message(chat_id, f"{user_stories[chat_id]['character']} {action}!\nPilih karakter lagi untuk melanjutkan")

def show_character_menu(chat_id, character_name):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(character_name)  # Tombol karakter
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    bot.send_message(chat_id, f"Karakter {character_name} siap!\nPilih nama karakter untuk memulai aksi", reply_markup=markup)

bot.polling()
