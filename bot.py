import os
import json
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from google import genai
from google.genai import types
import io
from datetime import datetime

# ==========================================
# KODE: ROMKOM ENGINE V.50.0 (FINAL PERFECTED)
# Deskripsi: UI REWORK + GEMINI 2.0 + IMPORT/EXPORT FIX
# ==========================================

# --- CONFIG ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Menggunakan SDK Google Gemini Terbaru
client = genai.Client(api_key=GEMINI_KEY)
SYSTEM_INSTRUCTION = "Kamu AI GM RomCom 21+. RESPON WAJIB 2 PARAGRAF. Gaya Indonesia kasual, sensual, puitis. ANTI-REPETISI."

bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = "experimental_db.json"

# --- DATABASE HANDLER ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)

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
    db[cid]["history"].append({"role": role, "parts": [text]})
    save_db(db)

# --- MENU SETUP ---
def setup_bot_commands():
    # Ini Menu Command (Tombol biru / )
    commands = [
        BotCommand("karakter", "Pilih karakter untuk interaksi"),
        BotCommand("lanjut_otomatis", "Lanjutkan cerita otomatis oleh AI")
    ]
    bot.set_my_commands(commands)

def get_main_menu():
    # Ini Menu Utama (Tombol besar di bawah layar)
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("➕ Cerita Baru"),
        KeyboardButton("📂 Import Cerita")
    )
    markup.add(
        KeyboardButton("👤 Tambah Karakter"),
        KeyboardButton("💾 Export Cerita")
    )
    markup.add(KeyboardButton("🔄 Reset"))
    return markup

# --- AI GENERATOR ---
def generate_ai_response(chat_id, prompt):
    user_data = get_user_data(chat_id)
    history = user_data["history"]
    context = f"[INFO] MC: {user_data['mc_name']}. Karakter lain: {', '.join(user_data['characters'])}.\n"
    full_prompt = context + prompt

    contents = []
    for msg in history:
        contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=full_prompt)]))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.9, top_p=0.95, top_k=64, max_output_tokens=1024,
    )

    try:
        # PENGGUNAAN GEMINI 2.0 FLASH (Lebih cerdas & anti error 404)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=config)
        text_response = response.text
        
        add_history(chat_id, "user", full_prompt)
        add_history(chat_id, "model", text_response)
        update_user_data(chat_id, "last_story", text_response)
        return text_response
    except Exception as e:
        return f"Terjadi kesalahan AI: {str(e)}"

# --- INLINE KEYBOARD (INTERAKSI CERITA) ---
def get_interactive_menu(chat_id):
    user_data = get_user_data(chat_id)
    markup = InlineKeyboardMarkup(row_width=2)
    
    if user_data['mc_name']:
        markup.add(InlineKeyboardButton(f"🗣 {user_data['mc_name']} (MC)", callback_data=f"act_mc"))
    
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
# COMMAND & MENU HANDLERS
# ==========================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    setup_bot_commands()
    # Hilangkan tombol bawah saat minta nama
    msg = bot.reply_to(message, "🌟 <b>Cerita RomKom 21+ Siap!</b>\n\nSilakan masukkan nama Tokoh Utama (Karaktermu):", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_mc_name)

def process_mc_name(message):
    chat_id = message.chat.id
    # Cegah format HTML crash dengan replace tag
    mc_name = message.text.strip().replace("<", "").replace(">", "")
    update_user_data(chat_id, "mc_name", mc_name)
    bot.send_message(chat_id, f"✅ Karakter Utama ditetapkan sebagai: <b>{mc_name}</b>.\n\nSilakan pilih menu di bawah layar 👇", parse_mode="HTML", reply_markup=get_main_menu())


# --- MENU BAWAH (REPLY KEYBOARD) HANDLERS ---

@bot.message_handler(func=lambda message: message.text == "➕ Cerita Baru")
def new_story(message):
    msg = bot.reply_to(message, "Tuliskan alur cerita awal yang kamu inginkan (Premis):", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_new_story)

def process_new_story(message):
    chat_id = message.chat.id
    plot = message.text
    bot.send_message(chat_id, "⏳ <b>Mengolah alur cerita...</b>", parse_mode="HTML", reply_markup=get_main_menu())
    
    update_user_data(chat_id, "history", [])
    prompt = f"Buat prolog cerita berdasarkan alur ini: {plot}. Ingat, buat tepat 2 paragraf."
    story = generate_ai_response(chat_id, prompt)
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id))

@bot.message_handler(func=lambda message: message.text == "👤 Tambah Karakter")
def add_character(message):
    msg = bot.reply_to(message, "Masukkan nama karakter baru yang ingin ditambahkan:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_add_char)

def process_add_char(message):
    chat_id = message.chat.id
    char_name = message.text.strip().replace("<", "").replace(">", "")
    user_data = get_user_data(chat_id)
    
    if char_name not in user_data['characters']:
        user_data['characters'].append(char_name)
        update_user_data(chat_id, "characters", user_data['characters'])
    
    bot.send_message(chat_id, f"✅ Karakter <b>{char_name}</b> berhasil ditambahkan ke daftar!", parse_mode="HTML", reply_markup=get_main_menu())
    if user_data['last_story']:
        bot.send_message(chat_id, "Pilih karakter untuk interaksi:", reply_markup=get_interactive_menu(chat_id))

@bot.message_handler(func=lambda message: message.text == "🔄 Reset")
def reset_data(message):
    chat_id = message.chat.id
    db = load_db()
    if str(chat_id) in db:
        del db[str(chat_id)]
        save_db(db)
    bot.reply_to(message, "🔄 Semua data telah direset. Ketik /start untuk mulai lagi.", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(func=lambda message: message.text == "💾 Export Cerita")
def export_story(message):
    chat_id = message.chat.id
    user_data = get_user_data(chat_id)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"story_{chat_id}_{timestamp}.json"
    
    json_data = json.dumps(user_data, indent=4, ensure_ascii=False, default=str)
    file_stream = io.BytesIO(json_data.encode('utf-8'))
    file_stream.name = file_name
    bot.send_document(chat_id, file_stream, caption="📂 File backup cerita Anda.")

@bot.message_handler(func=lambda message: message.text == "📂 Import Cerita")
def import_story(message):
    msg = bot.reply_to(message, "Silakan kirimkan file .json yang pernah di-export:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import_file)

def process_import_file(message):
    chat_id = message.chat.id
    if not message.document or not message.document.file_name.endswith('.json'):
        bot.send_message(chat_id, "❌ File tidak valid. Harus format .json! Batal import.", reply_markup=get_main_menu())
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        imported_data = json.loads(downloaded_file.decode('utf-8'))
        
        # Validasi kelengkapan JSON
        if not isinstance(imported_data, dict) or not all(k in imported_data for k in ("mc_name", "characters", "history", "last_story")):
            bot.send_message(chat_id, "❌ File JSON rusak atau bukan file cerita dari bot ini.", reply_markup=get_main_menu())
            return
        
        db = load_db()
        db[str(chat_id)] = imported_data
        save_db(db)
        
        bot.send_message(chat_id, "✅ Cerita berhasil di-import!\nMelanjutkan dari adegan terakhir...", reply_markup=get_main_menu())
        last_story = imported_data.get("last_story", "")
        if last_story:
            bot.send_message(chat_id, last_story, reply_markup=get_interactive_menu(chat_id))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Gagal membaca file: {str(e)}", reply_markup=get_main_menu())


# --- MENU COMMAND (TOMBOL BIRU / ) HANDLERS ---

@bot.message_handler(commands=['karakter'])
def cmd_karakter(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "👇 Pilih karakter di bawah ini untuk berinteraksi:", reply_markup=get_interactive_menu(chat_id))

@bot.message_handler(commands=['lanjut_otomatis'])
def cmd_lanjut(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏩ <b>Melanjutkan cerita otomatis...</b>", parse_mode="HTML")
    story = generate_ai_response(chat_id, "Lanjutkan cerita ini secara natural ke adegan berikutnya.")
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id))


# --- CALLBACK QUERIES (TOMBOL INLINE DI BAWAH CERITA) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    user_data = get_user_data(chat_id)
    action = call.data
    bot.answer_callback_query(call.id)

    if action == "act_mc":
        msg = bot.send_message(chat_id, f"Apa reaksi/tindakan <b>{user_data['mc_name']}</b>?", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{user_data['mc_name']} melakukan/mengatakan:")
        
    elif action.startswith("act_char_"):
        idx = int(action.split("_")[-1])
        char_name = user_data['characters'][idx]
        msg = bot.send_message(chat_id, f"Apa reaksi/tindakan <b>{char_name}</b>?", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, f"{char_name} melakukan/mengatakan:")

    elif action == "act_narrator":
        msg = bot.send_message(chat_id, "👁 <b>Narator:</b> Apa yang terjadi selanjutnya dalam cerita?", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_action, "Narator: ")

    elif action == "act_auto":
        bot.send_message(chat_id, "⏩ <b>Melanjutkan cerita otomatis...</b>", parse_mode="HTML")
        story = generate_ai_response(chat_id, "Lanjutkan cerita ini secara natural ke adegan berikutnya.")
        bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id))

def process_action(message, prefix_prompt):
    chat_id = message.chat.id
    user_input = message.text
    
    # Setelah mengetik, menu bawah dimunculkan lagi
    bot.send_message(chat_id, "⏳ <b>Menyusun cerita...</b>", parse_mode="HTML", reply_markup=get_main_menu())
    prompt = f"{prefix_prompt} {user_input}. Lanjutkan cerita berdasarkan tindakan ini dalam 2 paragraf."
    story = generate_ai_response(chat_id, prompt)
    bot.send_message(chat_id, story, reply_markup=get_interactive_menu(chat_id))

# ==========================================
# RUN BOT
# ==========================================
if __name__ == "__main__":
    print("🤖 Bot RomCom V.50 Berjalan Sempurna...")
    bot.infinity_polling()
