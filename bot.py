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
    bot.send_message(chat_id, "💘 Romkom 21+ V5.1 💘\nMasukkan nama karakter utama Anda:")
    story_data[chat_id] = {
        'main_char': None,
        'other_chars': [],
        'story_prompts': [],
        'scenes': []
    }

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    data = story_data.get(chat_id, {})
    
    if not data.get('main_char'):
        story_data[chat_id]['main_char'] = message.text
        show_main_menu(chat_id)
    
    elif message.text == '1. Narator':
        bot.send_message(chat_id, "📖 Masukkan prompt narasi cerita (contoh: 'adegan mesra di pantai'):")
        bot.register_next_step_handler(message, process_narration)
        
    elif message.text == '6. Tambah Karakter':
        bot.send_message(chat_id, "👥 Masukkan nama karakter baru:")
        bot.register_next_step_handler(message, add_character)

def process_narration(message):
    chat_id = message.chat.id
    prompt = message.text
    response = model.generate_content(f"Buat adegan romkom dewasa dengan karakter utama {story_data[chat_id]['main_char']}. Prompt: {prompt}")
    story_data[chat_id]['scenes'].append(response.text)
    bot.send_message(chat_id, f"✨ Adegan baru:\n\n{response.text}")

def add_character(message):
    chat_id = message.chat.id
    new_char = message.text
    story_data[chat_id]['other_chars'].append(new_char)
    bot.send_message(chat_id, f"Karakter '{new_char}' telah ditambahkan!")
    show_main_menu(chat_id)

def show_main_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"🎭 {story_data[chat_id]['main_char']} 🎭")
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    markup.row('6. Tambah Karakter', '7. Undo')
    bot.send_message(chat_id, 
        f"Main Character: {story_data[chat_id]['main_char']}\n"
        f"Other Characters: {', '.join(story_data[chat_id]['other_chars'])}",
        reply_markup=markup)

bot.polling()
