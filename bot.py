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
# 1. CONFIG & INITIALIZATION
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
# 2. DATABASE HANDLER (Sistem File Lokal)
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
        print(f"Gagal simpan file: {e}")

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
# 3. MENU & UI GENERATOR
# ==========================================
def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("➕ Cerita Baru"), KeyboardButton("📂 Import Cerita"))
    markup.add(KeyboardButton("👤 Tambah Karakter"), KeyboardButton("💾 Export Cerita"))
    markup.add(KeyboardButton("🔄 Reset"))
    return markup

def get_interactive_menu(chat_id):
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
    # Ambil 10 history terakhir saja biar hemat token & stabil
    for msg in history[-10:]:
        contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context + prompt)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.9,
    )

    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=contents, config=config)
        text_response = response.text
        
        # Simpan ke history
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
# 5. CORE HANDLERS (START, MC, ETC)
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🌟 <b>Bot RomKom V.50 (Railway Mode)</b>\n\nMasukkan nama Karakter Utamamu (MC):", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_mc_name)

def process_mc_name(message):
    chat_id = message.chat.id
    mc_name = message.text.strip()[:30] # Limit nama biar gak rusak UI
    update_user_data(chat_id, "mc_name", mc_name)
    bot.send_message(chat_id, f"✅ MC kamu: <b>{mc_name}</b>\n\nSilakan pilih menu di bawah!", parse_mode="HTML", reply_markup=get_main_menu())

# ==========================================
# 6. FIXED EXPORT & IMPORT LOGIC
# ==========================================
@bot.message_handler(func=lambda message: message.text == "💾 Export Cerita")
def export_handler(message):
    chat_id = message.chat.id
    user_data = get_user_data(chat_id)
    
    if not user_data.get("mc_name"):
        return bot.reply_to(message, "❌ Belum ada data. Mulai cerita dulu.")

    try:
        # Generate JSON file in memory
        json_string = json.dumps(user_data, indent=4, ensure_ascii=False)
        file_stream = io.BytesIO(json_string.encode('utf-8'))
        file_stream.name = f"RomKom_Backup_{chat_id}.json"
        file_stream.seek(0) # PENTING: Kembali ke titik nol
        
        bot.send_document(
            chat_id, 
            file_stream, 
            caption="📂 <b>Ini file backup kamu!</b>\nSimpan baik-baik. Kalau server restart, kirim file ini via menu Import.",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(message, f"⚠️ Gagal Export: {str(e)}")

@bot.message_handler(func=lambda message: message.text == "📂 Import Cerita")
def import_handler(message):
    msg = bot.reply_to(message, "📤 <b>Kirimkan file .json backup kamu:</b>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import_file)

def process_import_file(message):
    chat_id = message.chat.id
    if not message.document:
        return bot.send_message(chat_id, "❌ Batal. Kamu tidak mengirim file.", reply_markup=get_main_menu())

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        data = json.loads(downloaded_file.decode('utf-8'))
        
        # Validasi Data
        if "mc_name" not in data:
            return bot.send_message(chat_id, "❌ File JSON tidak valid!", reply_markup=get_main_menu())
            
        db = load_db()
        db[str(chat_id)] = data
        save_db(db)
        
        bot.send_message(chat_id, "✅ <b>Data Berhasil Dimuat!</b>", parse_mode="HTML", reply_markup=get_main_menu())
        if data.get("last_story"):
            bot.send_message(chat_id, "<b>Adegan Terakhir:</b>\n" + data["last_story"], parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Gagal Import: {str(e)}", reply_markup=get_main_menu())

# ==========================================
# 7. INTERACTIVE STORY HANDLERS
# ==========================================
@bot.message_handler(func=lambda message: message.text == "➕ Cerita Baru")
def new_story_start(message):
    msg = bot.reply_to(message, "Tuliskan premis/awal cerita yang kamu inginkan:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_new_story)

def process_new_story(message):
    chat_id = message.chat.id
    update_user_data(chat_id, "history", []) # Reset history untuk cerita baru
    bot.send_message(chat_id, "⏳ <i>Menyusun Prolog...</i>", parse_mode="HTML")
    
    story = generate_ai_response(chat_id, f"Buat prolog menarik dari alur ini: {message.text}")
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    user_data = get_user_data(chat_id)
    bot.answer_callback_query(call.id)

    if call.data == "act_mc":
        msg = bot.send_message(chat_id, f"Tindakan <b>{user_data['mc_name']}</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{user_data['mc_name']}:")
    
    elif call.data.startswith("act_char_"):
        idx = int(call.data.split("_")[-1])
        name = user_data['characters'][idx]
        msg = bot.send_message(chat_id, f"Tindakan <b>{name}</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{name}:")

    elif call.data == "act_auto":
        bot.send_message(chat_id, "⏩ <i>Melanjutkan adegan...</i>", parse_mode="HTML")
        story = generate_ai_response(chat_id, "Lanjutkan cerita secara natural.")
        bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

    elif call.data == "act_narrator":
        msg = bot.send_message(chat_id, "👁 <b>Narator:</b> Apa yang terjadi selanjutnya?", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, "Narator:")

def process_action(message, prefix):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ <i>Mengetik...</i>", parse_mode="HTML", reply_markup=get_main_menu())
    story = generate_ai_response(chat_id, f"{prefix} {message.text}")
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

# ==========================================
# 8. OTHER HANDLERS
# ==========================================
@bot.message_handler(func=lambda message: message.text == "👤 Tambah Karakter")
def add_char_handler(message):
    msg = bot.reply_to(message, "Ketik nama karakter baru:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, save_new_char)

def save_new_char(message):
    chat_id = message.chat.id
    name = message.text.strip()
    data = get_user_data(chat_id)
    if name not in data['characters']:
        data['characters'].append(name)
        update_user_data(chat_id, "characters", data['characters'])
    bot.send_message(chat_id, f"✅ <b>{name}</b> ditambahkan!", parse_mode="HTML", reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: message.text == "🔄 Reset")
def reset_handler(message):
    db = load_db()
    db.pop(str(message.chat.id), None)
    save_db(db)
    bot.reply_to(message, "🔄 Data ceritamu sudah dihapus bersih. Ketik /start lagi.", reply_markup=ReplyKeyboardRemove())

# ==========================================
# 9. RUN ENGINE
# ==========================================
if __name__ == "__main__":
    print("🤖 Bot RomCom V.50 Berjalan Sempurna...")
    # Menghindari Error 409 di Railway dengan parameter timeout
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
