import os
import json
import telebot
import io
from datetime import datetime
from telebot.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    BotCommand, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove
)
from google import genai
from google.genai import types

# ==========================================
# 1. KONFIGURASI & INISIALISASI
# ==========================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Menggunakan SDK Google Gemini Terbaru
client = genai.Client(api_key=GEMINI_KEY)
SYSTEM_INSTRUCTION = (
    "Kamu AI GM RomCom 21+. RESPON WAJIB 2 PARAGRAF. "
    "Gaya Indonesia kasual, sensual, puitis. ANTI-REPETISI."
)

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = "experimental_db.json"

# ==========================================
# 2. DATABASE HANDLER
# ==========================================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Gagal simpan database: {e}")

def get_user_data(chat_id):
    db = load_db()
    cid = str(chat_id)
    if cid not in db:
        db[cid] = {"mc_name": "", "characters": [], "history": [], "last_story": ""}
        save_db(db)
    return db[cid]

def update_user_data(chat_id, key, value):
    db = load_db()
    cid = str(chat_id)
    if cid not in db:
        db[cid] = {"mc_name": "", "characters": [], "history": [], "last_story": ""}
    db[cid][key] = value
    save_db(db)

# ==========================================
# 3. SETUP MENU & KEYBOARD
# ==========================================
def setup_bot_commands():
    # Ini Menu Command (Tombol biru di pojok kiri bawah)
    commands = [
        BotCommand("start", "Mulai Ulang / Masukkan Nama MC"),
        BotCommand("karakter", "Pilih karakter untuk interaksi"),
        BotCommand("lanjut_otomatis", "Lanjutkan cerita otomatis"),
        BotCommand("reset", "Hapus semua progress cerita")
    ]
    bot.set_my_commands(commands)

def get_main_menu():
    # Custom Keyboard Utama (Tombol besar di bawah)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=2)
    markup.add(KeyboardButton("➕ Cerita Baru"), KeyboardButton("📂 Import Cerita"))
    markup.add(KeyboardButton("👤 Tambah Karakter"), KeyboardButton("💾 Export Cerita"))
    markup.add(KeyboardButton("🔄 Reset"))
    return markup

def get_interactive_menu(chat_id):
    # Inline Keyboard (Tombol di bawah teks cerita)
    user_data = get_user_data(chat_id)
    markup = InlineKeyboardMarkup(row_width=2)
    
    if user_data.get('mc_name'):
        markup.add(InlineKeyboardButton(f"🗣 {user_data['mc_name']} (MC)", callback_data="act_mc"))
    
    char_buttons = []
    for idx, char_name in enumerate(user_data.get('characters', [])):
        char_buttons.append(InlineKeyboardButton(f"👤 {char_name}", callback_data=f"act_char_{idx}"))
    
    if char_buttons:
        markup.add(*char_buttons)
    
    markup.add(
        InlineKeyboardButton("⏩ Lanjut Otomatis", callback_data="act_auto"),
        InlineKeyboardButton("👁 Narator", callback_data="act_narrator")
    )
    return markup

# ==========================================
# 4. AI ENGINE (GEMINI 2.0 FLASH)
# ==========================================
def generate_ai_response(chat_id, prompt):
    user_data = get_user_data(chat_id)
    history = user_data.get("history", [])
    context = f"[INFO] MC: {user_data['mc_name']}. Karakter lain: {', '.join(user_data['characters'])}.\n"
    
    contents = []
    # Batasi history 10 pesan terakhir agar respons tetap cepat & relevan
    for msg in history[-10:]:
        contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context + prompt)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.9,
    )

    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=config)
        text_response = response.text
        
        # Simpan History & Status Terakhir
        db = load_db()
        cid = str(chat_id)
        db[cid]["history"].append({"role": "user", "parts": [prompt]})
        db[cid]["history"].append({"role": "model", "parts": [text_response]})
        db[cid]["last_story"] = text_response
        save_db(db)
        
        return text_response
    except Exception as e:
        return f"⚠️ Kesalahan AI: {str(e)}"

# ==========================================
# 5. HANDLERS (START & INPUT MC)
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    setup_bot_commands() # Update menu command setiap start
    bot.reply_to(message, "🌟 <b>Selamat Datang di RomKom Engine!</b>\n\nSiapa nama Karakter Utamamu (MC)?", 
                 parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_mc_name)

def process_mc_name(message):
    chat_id = message.chat.id
    mc_name = message.text.strip()[:25]
    update_user_data(chat_id, "mc_name", mc_name)
    bot.send_message(chat_id, f"✅ Nama MC ditetapkan: <b>{mc_name}</b>\n\nSilakan pilih menu di bawah layar 👇", 
                     parse_mode="HTML", reply_markup=get_main_menu())

# ==========================================
# 6. IMPORT & EXPORT HANDLERS
# ==========================================
@bot.message_handler(func=lambda message: message.text == "💾 Export Cerita")
def export_handler(message):
    chat_id = message.chat.id
    user_data = get_user_data(chat_id)
    
    if not user_data.get("mc_name"):
        return bot.reply_to(message, "❌ Tidak ada data. Mulai cerita baru dulu!", reply_markup=get_main_menu())

    try:
        json_data = json.dumps(user_data, indent=4, ensure_ascii=False)
        stream = io.BytesIO(json_data.encode('utf-8'))
        stream.name = f"RomKom_Backup_{chat_id}.json"
        stream.seek(0)
        
        bot.send_document(chat_id, stream, caption="📂 <b>Backup Cerita Kamu</b>\nSimpan file ini. Jika server restart, gunakan menu Import.", 
                          parse_mode="HTML", reply_markup=get_main_menu())
    except Exception as e:
        bot.reply_to(message, f"⚠️ Gagal Export: {e}", reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: message.text == "📂 Import Cerita")
def import_handler(message):
    msg = bot.reply_to(message, "📤 <b>Kirimkan file .json backup kamu:</b>", 
                       parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import_file)

def process_import_file(message):
    chat_id = message.chat.id
    if not message.document:
        return bot.send_message(chat_id, "❌ Batal. Kamu tidak mengirim file.", reply_markup=get_main_menu())

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        data = json.loads(downloaded.decode('utf-8'))
        
        db = load_db()
        db[str(chat_id)] = data
        save_db(db)
        
        bot.send_message(chat_id, "✅ <b>Import Berhasil!</b>", parse_mode="HTML", reply_markup=get_main_menu())
        if data.get("last_story"):
            bot.send_message(chat_id, f"<b>Adegan Terakhir:</b>\n\n{data['last_story']}", 
                             parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Gagal Import: {e}", reply_markup=get_main_menu())

# ==========================================
# 7. ALUR CERITA & INTERAKSI
# ==========================================
@bot.message_handler(func=lambda message: message.text == "➕ Cerita Baru")
def new_story_start(message):
    msg = bot.reply_to(message, "Tuliskan premis/awal cerita yang kamu inginkan:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_new_story)

def process_new_story(message):
    chat_id = message.chat.id
    update_user_data(chat_id, "history", [])
    bot.send_message(chat_id, "⏳ <i>Menyusun Prolog...</i>", parse_mode="HTML")
    
    story = generate_ai_response(chat_id, f"Buat prolog dari alur ini: {message.text}")
    bot.send_message(chat_id, story, parse_mode="HTML", 
                     reply_markup=get_interactive_menu(chat_id))
    # Selalu munculkan menu utama di akhir aksi
    bot.send_message(chat_id, "👇 Menu Utama:", reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    user_data = get_user_data(chat_id)
    bot.answer_callback_query(call.id)

    if call.data == "act_mc":
        msg = bot.send_message(chat_id, f"Apa yang dilakukan <b>{user_data['mc_name']}</b>?", 
                               parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{user_data['mc_name']}:")
    
    elif call.data.startswith("act_char_"):
        idx = int(call.data.split("_")[-1])
        name = user_data['characters'][idx]
        msg = bot.send_message(chat_id, f"Apa yang dilakukan <b>{name}</b>?", 
                               parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{name}:")

    elif call.data == "act_auto":
        bot.send_message(chat_id, "⏩ <i>Melanjutkan adegan...</i>", parse_mode="HTML")
        story = generate_ai_response(chat_id, "Lanjutkan cerita secara natural.")
        bot.send_message(chat_id, story, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
        bot.send_message(chat_id, "👇 Menu Utama:", reply_markup=get_main_menu())

    elif call.data == "act_narrator":
        msg = bot.send_message(chat_id, "👁 Apa yang terjadi selanjutnya?", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, "Narator:")

def process_action(message, prefix):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ <i>AI sedang mengetik...</i>", parse_mode="HTML")
    story = generate_ai_response(chat_id, f"{prefix} {message.text}")
    bot.send_message(chat_id, story, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
    # Kirim menu utama untuk memastikan tombol bawah tidak hilang
    bot.send_message(chat_id, "👇 Menu Utama:", reply_markup=get_main_menu())

# ==========================================
# 8. KARAKTER & RESET
# ==========================================
@bot.message_handler(func=lambda message: message.text == "👤 Tambah Karakter")
def add_char_handler(message):
    msg = bot.reply_to(message, "Masukkan nama karakter baru:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, save_new_char)

def save_new_char(message):
    chat_id = message.chat.id
    name = message.text.strip()
    data = get_user_data(chat_id)
    if name not in data['characters']:
        data['characters'].append(name)
        update_user_data(chat_id, "characters", data['characters'])
    bot.send_message(chat_id, f"✅ <b>{name}</b> ditambahkan!", 
                     parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: message.text == "🔄 Reset")
def reset_handler(message):
    db = load_db()
    db.pop(str(message.chat.id), None)
    save_db(db)
    bot.reply_to(message, "🔄 Data ceritamu sudah dihapus. Ketik /start.", reply_markup=ReplyKeyboardRemove())

# ==========================================
# 9. RUNNING
# ==========================================
if __name__ == "__main__":
    print("🤖 Bot RomCom V.50.1 Active...")
    setup_bot_commands()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
