import os
import telebot
import google.generativeai as genai

# Konfigurasi Gemini AI
genai.configure(api_key=os.environ['GEMINI_API_KEY'])
model = genai.GenerativeModel('gemini-3-flash-preview')

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
story_data = {}

@bot.message_handler(commands=['start'])
def start(message):
    """Reset game ke state awal"""
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔥 Romkom 21+ V4.0 🔥\nMasukkan nama karakter utama:")
    story_data[chat_id] = {
        'main_char': None,
        'other_chars': [],
        'history': [],
        'last_response': None
    }

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    data = story_data.get(chat_id, {})
    
    if not data.get('main_char'):
        # Tahap input karakter utama
        story_data[chat_id]['main_char'] = message.text
        show_main_menu(chat_id)
        
    elif message.text == f"🎭 {data['main_char']} 🎭":
        ask_for_action(chat_id)
        
    elif message.text == '1. Narator':
        generate_narration(chat_id)
        
    elif message.text == '2. Lanjutkan':
        continue_story(chat_id)
        
    elif message.text == '5. Reset':
        start(message)
        
    elif message.text == '6. Tambah Karakter':
        bot.send_message(chat_id, "Masukkan nama karakter baru:")
        bot.register_next_step_handler(message, add_new_character)
        
    elif message.text == '7. Undo':
        undo_last_action(chat_id)
        
    elif message.text.startswith('aksi:'):
        process_action(chat_id, message.text[5:].strip())

def show_main_menu(chat_id):
    """Tampilkan menu utama dengan semua opsi"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"🎭 {story_data[chat_id]['main_char']} 🎭")
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    markup.row('6. Tambah Karakter', '7. Undo')
    bot.send_message(chat_id, 
        f"✨ {story_data[chat_id]['main_char']} siap berpetualang!\n"
        "Pilih tombol untuk melanjutkan",
        reply_markup=markup)

def ask_for_action(chat_id):
    """Minta input aksi karakter utama"""
    bot.send_message(chat_id,
        f"💋 Tulis aksi untuk {story_data[chat_id]['main_char']}:\n"
        "Format: 'aksi: [deskripsi aksi]'\n"
        "Contoh: 'aksi: mencium gadis di bar'")

def generate_narration(chat_id):
    """Generate narasi menggunakan Gemini AI"""
    prompt = f"Buat narasi 2 paragraf untuk cerita romkom dewasa dengan karakter {story_data[chat_id]['main_char']}"
    response = model.generate_content(prompt)
    story_data[chat_id]['last_response'] = response.text
    bot.send_message(chat_id, response.text)

def continue_story(chat_id):
    """Lanjutkan cerita otomatis"""
    if story_data[chat_id]['history']:
        last_scene = story_data[chat_id]['history'][-1]
        prompt = f"Lanjutkan scene romkom dewasa ini:\n{last_scene}"
        response = model.generate_content(prompt)
        story_data[chat_id]['last_response'] = response.text
        bot.send_message(chat_id, response.text)
    else:
        bot.send_message(chat_id, "Belum ada history cerita. Pilih 'Narator' dulu")

bot.polling()
