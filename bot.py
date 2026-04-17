import os
import telebot
import google.generativeai as genai

genai.configure(api_key=os.environ['GEMINI_API_KEY'])
model = genai.GenerativeModel('gemini-3-flash-preview')

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
story_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔥 Hot Romkom V7 🔥\nMasukkan nama karakter utama:")
    story_data[chat_id] = {
        'main_char': None,
        'other_chars': [],
        'scenes': []
    }

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    
    if not story_data[chat_id]['main_char']:
        story_data[chat_id]['main_char'] = message.text
        show_main_menu(chat_id)
    elif message.text == '1. Narator':
        ask_for_narration(chat_id)
    elif message.text == '6. Tambah Karakter':
        ask_for_new_character(chat_id)

def ask_for_narration(chat_id):
    bot.send_message(chat_id, "📝 Masukkan prompt narasi (contoh: 'adegan panas di lift'):")
    bot.register_next_step_handler_by_chat_id(chat_id, process_narration)

def process_narration(message):
    chat_id = message.chat.id
    prompt = f"Karakter: {story_data[chat_id]['main_char']}\n" \
             f"Karakter lain: {', '.join(story_data[chat_id]['other_chars'])}\n" \
             f"Prompt: {message.text}\n" \
             "(Max 3 paragraf, bahasa Indonesia)"
    
    response = model.generate_content(prompt)
    story_data[chat_id]['scenes'].append(response.text)
    
    for part in [response.text[i:i+4000] for i in range(0, len(response.text), 4000)]:
        bot.send_message(chat_id, f"🔥 Adegan:\n\n{part}")
    
    show_main_menu(chat_id)

def show_main_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"💋 {story_data[chat_id]['main_char']} 💋")
    for char in story_data[chat_id]['other_chars']:
        markup.row(f"✨ {char} ✨")
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    markup.row('6. Tambah Karakter', '7. Undo')
    bot.send_message(chat_id, "Pilih menu:", reply_markup=markup)

bot.polling()
