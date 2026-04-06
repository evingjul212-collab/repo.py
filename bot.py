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
# CONFIG & INITIALIZATION
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
# DATABASE HANDLER (LOCAL FILE)
# ==========================================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            return {}
    return {}

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush() # Paksa tulis ke disk
            os.fsync(f.fileno()) # Pastikan benar-benar tersimpan
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

def add_history(chat_id, role, text):
    db = load_db()
    cid = str(chat_id)
    if cid not in db:
        db[cid] = {"mc_name": "", "characters": [], "history": [], "last_story": ""}
    # Batasi history agar tidak terlalu berat (max 20 pesan terakhir)
    db[cid]["history"].append({"role": role, "parts": [text]})
    if len(db[cid]["history"]) > 20:
        db[cid]["history"] = db[cid]["history"][-20:]
    save_db(db)

# ==========================================
# UI & MENU HELPERS
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
    
    if user_data['mc_name']:
        markup.add(InlineKeyboardButton(f"🗣 {user_data['mc_name']} (MC)", callback_data="act_mc"))
    
    char_buttons = []
    for idx, char_name in enumerate(user_data['characters']):
        char_buttons.append(InlineKeyboardButton(f"👤 {char_name}", callback_data=f"act_char_{idx}"))
    
    if char_buttons:
        markup.add(*char_buttons)
    
    markup.add(
        InlineKeyboardButton("⏩ Lanjut Otomatis", callback_data="act_auto"),
        InlineKeyboardButton("👁 Narator", callback_data="act_narrator")
    )
    return markup

# ==========================================
# AI ENGINE (GEMINI 2.0 FLASH)
# ==========================================
def generate_ai_response(chat_id, prompt):
    user_data = get_user_data(chat_id)
    history = user_data["history"]
    context = f"[INFO] MC: {user_data['mc_name']}. Karakter lain: {', '.join(user_data['characters'])}.\n"
    
    contents = []
    for msg in history:
        contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context + prompt)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.9,
        max_output_tokens=1024,
    )

    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=config)
        text_response = response.text
        
        # Simpan History
        add_history(chat_id, "user", prompt)
        add_history(chat_id, "model", text_response)
        update_user_data(chat_id, "last_story", text_response)
        return text_response
    except Exception as e:
        return f"⚠️ Kesalahan AI: {str(e)}"

# ==========================================
# COMMAND HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "🌟 <b>Bot RomCom V.50 (Railway Edition)</b>\n\n"
        "Silakan masukkan nama Karakter Utamamu (MC):", 
        parse_mode="HTML", 
        reply_markup=ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(message, process_mc_name)

def process_mc_name(message):
    mc_name = message.text.strip().replace("<", "").replace(">", "")
    update_user_data(message.chat.id, "mc_name", mc_name)
    bot.send_message(
        message.chat.id, 
        f"✅ MC: <b>{mc_name}</b>\n\nGunakan menu di bawah untuk beraksi!", 
        parse_mode="HTML", 
        reply_markup=get_main_menu()
    )

# ==========================================
# IMPORT & EXPORT LOGIC (FIXED)
# ==========================================
@bot.message_handler(func=lambda message: message.text == "💾 Export Cerita")
def export_story(message):
    chat_id = message.chat.id
    user_data = get_user_data(chat_id)
    
    if not user_data.get("mc_name"):
        bot.reply_to(message, "❌ Tidak ada data untuk di-export.")
        return

    try:
        json_data = json.dumps(user_data, indent=4, ensure_ascii=False)
        file_stream = io.BytesIO(json_data.encode('utf-8'))
        file_stream.name = f"RomKom_Backup_{chat_id}.json"
        
        # FIX: Kembalikan pointer ke awal sebelum kirim
        file_stream.seek(0)
        
        bot.send_document(
            chat_id, 
            file_stream, 
            caption="📂 <b>File Backup Kamu</b>\n\nSimpan file ini. Jika server restart, kirim file ini via menu <b>Import Cerita</b>.",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Gagal Export: {e}")

@bot.message_handler(func=lambda message: message.text == "📂 Import Cerita")
def import_story(message):
    msg = bot.reply_to(message, "Kirimkan file <b>.json</b> hasil export sebelumnya:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import_file)

def process_import_file(message):
    chat_id = message.chat.id
    if not message.document or not message.document.file_name.endswith('.json'):
        bot.send_message(chat_id, "❌ Batal. Harus file .json!", reply_markup=get_main_menu())
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        imported_data = json.loads(downloaded_file.decode('utf-8'))
        
        db = load_db()
        db[str(chat_id)] = imported_data
        save_db(db)
        
        bot.send_message(chat_id, "✅ <b>Import Berhasil!</b>", parse_mode="HTML", reply_markup=get_main_menu())
        if imported_data.get("last_story"):
            bot.send_message(chat_id, imported_data["last_story"], reply_markup=get_interactive_menu(chat_id))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Gagal Import: {e}", reply_markup=get_main_menu())

# ==========================================
# STORY LOGIC HANDLERS
# ==========================================
@bot.message_handler(func=lambda message: message.text == "➕ Cerita Baru")
def new_story(message):
    msg = bot.reply_to(message, "Tuliskan premis/alur awal ceritamu:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_new_story)

def process_new_story(message):
    chat_id = message.chat.id
    update_user_data(chat_id, "history", [])
    bot.send_message(chat_id, "⏳ <i>Menyusun Prolog...</i>", parse_mode="HTML")
    
    story = generate_ai_response(chat_id, f"Buat prolog dari alur: {message.text}")
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_data = get_user_data(chat_id)
    action = call.data
    bot.answer_callback_query(call.id)

    if action == "act_mc":
        msg = bot.send_message(chat_id, f"Tindakan <b>{user_data['mc_name']}</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{user_data['mc_name']}:")
    
    elif action.startswith("act_char_"):
        idx = int(action.split("_")[-1])
        name = user_data['characters'][idx]
        msg = bot.send_message(chat_id, f"Tindakan <b>{name}</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{name}:")

    elif action == "act_auto":
        bot.send_message(chat_id, "⏩ <i>Melanjutkan...</i>", parse_mode="HTML")
        story = generate_ai_response(chat_id, "Lanjutkan adegan secara natural.")
        bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

    elif action == "act_narrator":
        msg = bot.send_message(chat_id, "👁 Apa yang terjadi selanjutnya?", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, "Narator:")

def process_action(message, prefix):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ <i>Mengetik...</i>", parse_mode="HTML", reply_markup=get_main_menu())
    story = generate_ai_response(chat_id, f"{prefix} {message.text}")
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id), parse_mode="HTML")

@bot.message_handler(func=lambda message: message.text == "🔄 Reset")
def reset_data(message):
    db = load_db()
    db.pop(str(message.chat.id), None)
    save_db(db)
    bot.reply_to(message, "🔄 Data dihapus. Ketik /start.", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(func=lambda message: message.text == "👤 Tambah Karakter")
def add_char_start(message):
    msg = bot.reply_to(message, "Nama Karakter Baru:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, do_add_char)

def do_add_char(message):
    name = message.text.strip()
    data = get_user_data(message.chat.id)
    if name not in data['characters']:
        data['characters'].append(name)
        update_user_data(message.chat.id, "characters", data['characters'])
    bot.send_message(message.chat.id, f"✅ {name} ditambahkan!", reply_markup=get_main_menu())

# ==========================================
# RUN BOT
# ==========================================
if __name__ == "__main__":
    print("🤖 Bot RomCom V.50 Active...")
    # Infinity polling untuk handle reconnect otomatis di Railway
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
