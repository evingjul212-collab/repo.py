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
    bot.send_message(chat_id, "💞 Romkom 21+ V5.2 💞\nMasukkan nama karakter utama Anda:")
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
        bot.send_message(chat_id, "📖 Masukkan prompt narasi (contoh: 'adegan mesra di kamar hotel'):")
        bot.register_next_step_handler(message, process_narration)
    
    elif message.text == '6. Tambah Karakter':
        bot.send_message(chat_id, "👥 Masukkan nama karakter baru:")
        bot.register_next_step_handler(message, add_character)
    
    elif any(char in message.text for char in data['other_chars']):
        char_name = message.text[3:-3]  # Extract from format "✨ Name ✨"
        ask_character_action(chat_id, char_name)

def show_main_menu(chat_id):
    """Tampilkan menu dengan tombol karakter utama dan karakter pendukung"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    # Tombol karakter utama
    markup.row(f"✨ {story_data[chat_id]['main_char']} ✨")
    
    # Tombol karakter pendukung
    for char in story_data[chat_id]['other_chars']:
        markup.row(f"✨ {char} ✨")
    
    # Menu utama
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    markup.row('6. Tambah Karakter', '7. Undo')
    
    bot.send_message(chat_id, 
        f"💋 Pilih karakter untuk berinteraksi:",
        reply_markup=markup)
def process_narration(message):
    chat_id = message.chat.id
    prompt = f"Buat cerita romkom dewasa dengan:\nKarakter utama: {story_data[chat_id]['main_char']}\nKarakter lain: {', '.join(story_data[chat_id]['other_chars'])}\nPrompt: {message.text}\n(Max 3000 karakter)"
    
    try:
        response = model.generate_content(prompt)
        # Potong cerita menjadi bagian-bagian 4000 karakter
        for i in range(0, len(response.text), 4000):
            part = response.text[i:i+4000]
            bot.send_message(chat_id, f"📖 Bagian {i//4000 + 1}:\n\n{part}")
        
        story_data[chat_id]['scenes'].append(response.text)
    except Exception as e:
        bot.send_message(chat_id, f"Error: {str(e)}")
    
    show_main_menu(chat_id)
bot.polling()
