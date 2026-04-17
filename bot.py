import os
import telebot
import google.generativeai as genai

# Initialize with all requested features
genai.configure(api_key=os.environ['GEMINI_API_KEY'])
model = genai.GenerativeModel('gemini-3-flash-preview')

bot = telebot.TeleBot(os.environ['TELEGRAM_TOKEN'])
story_data = {}

def start(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "💘 Ultimate Romkom Bot 💘\nMasukkan nama karakter utama:")
    story_data[chat_id] = {
        'main_char': None,
        'other_chars': [],
        'scenes': []
    }

@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    
    # Karakter utama belum diisi
    if not story_data[chat_id]['main_char']:
        story_data[chat_id]['main_char'] = message.text
        show_full_menu(chat_id)
    
    # Tombol Narator
    elif message.text == '1. Narator':
        bot.send_message(chat_id, "📖 Masukkan prompt cerita (contoh: 'adegan mesra di restoran'):")
        bot.register_next_step_handler(message, generate_story)
    
    # Tombol Lanjutkan
    elif message.text == '2. Lanjutkan':
        continue_last_scene(chat_id)
    
    # Tombol Tambah Karakter
    elif message.text == '6. Tambah Karakter':
        bot.send_message(chat_id, "👥 Masukkan nama karakter baru:")
        bot.register_next_step_handler(message, add_character)

def show_full_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(f"🌟 {story_data[chat_id]['main_char']} 🌟")
    for char in story_data[chat_id]['other_chars']:
        markup.row(f"✨ {char} ✨")
    markup.row('1. Narator', '2. Lanjutkan')
    markup.row('3. Save', '4. Load', '5. Reset')
    markup.row('6. Tambah Karakter', '7. Undo')
    bot.send_message(chat_id, "Pilih karakter atau menu:", reply_markup=markup)

def generate_story(message):
    chat_id = message.chat.id
    prompt = f"Buat cerita romkom dewasa dengan:\n- Karakter: {story_data[chat_id]['main_char']}\n- Karakter lain: {', '.join(story_data[chat_id]['other_chars'])}\n- Adegan: {message.text}"
    
    response = model.generate_content(prompt)
    story_data[chat_id]['scenes'].append(response.text)
    
    # Kirim per bagian
    for i in range(0, len(response.text), 4000):
        bot.send_message(chat_id, f"📖 Bagian {i//4000 + 1}:\n\n{response.text[i:i+4000]}")
    
    show_full_menu(chat_id)

bot.polling()
