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
# 1. KONFIGURASI
# ==========================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_KEY)
SYSTEM_INSTRUCTION = (
    "Kamu AI GM RomCom 21+. RESPON WAJIB 2 PARAGRAF (Minimal 100 kata). "
    "Gaya Indonesia kasual, sensual, puitis. "
    "Patuhi detail karakter yang diberikan agar konsisten."
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
        except Exception: return {}
    return {}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_data(chat_id):
    db = load_db()
    cid = str(chat_id)
    if cid not in db:
        db[cid] = {"mc": {"name": "", "desc": ""}, "characters": [], "history": [], "last_story": ""}
        save_db(db)
    return db[cid]

# ==========================================
# 3. KEYBOARD GENERATOR
# ==========================================
def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("➕ Cerita Baru"), KeyboardButton("📂 Import Cerita"))
    markup.add(KeyboardButton("👤 Tambah Karakter"), KeyboardButton("💾 Export Cerita"))
    markup.add(KeyboardButton("🔄 Reset"))
    return markup

def get_interactive_menu(chat_id):
    data = get_user_data(chat_id)
    markup = InlineKeyboardMarkup(row_width=2)
    
    if data['mc']['name']:
        markup.add(InlineKeyboardButton(f"🗣 {data['mc']['name']}", callback_data="act_mc"))
    
    for idx, char in enumerate(data['characters']):
        markup.add(InlineKeyboardButton(f"👤 {char['name']}", callback_data=f"act_char_{idx}"))
    
    markup.add(
        InlineKeyboardButton("⏩ Lanjut Otomatis", callback_data="act_auto"),
        InlineKeyboardButton("👁 Narator", callback_data="act_narrator")
    )
    markup.add(InlineKeyboardButton("🔄 Ulang Respon (Regen)", callback_data="act_regen"))
    return markup

# ==========================================
# 4. AI ENGINE
# ==========================================
def generate_ai_response(chat_id, prompt, is_regen=False):
    db = load_db()
    cid = str(chat_id)
    data = db[cid]
    
    # Jika Regen, hapus histori terakhir (User & Model)
    if is_regen and len(data['history']) >= 2:
        data['history'] = data['history'][:-2]

    # Ambil konteks karakter
    chars_info = "\n".join([f"- {c['name']}: {c['desc']}" for c in data['characters']])
    context = (
        f"MC: {data['mc']['name']} ({data['mc']['desc']})\n"
        f"NPC:\n{chars_info}\n"
        f"PERINTAH: Tulis 2 paragraf deskriptif puitis.\n"
    )
    
    contents = []
    # Ambil 6 pesan terakhir agar history export tidak bengkak & AI fokus
    for msg in data['history'][-6:]:
        contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context + prompt)]))

    try:
        config = types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.9)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=config)
        text = response.text
        
        # Simpan History
        data["history"].append({"role": "user", "parts": [prompt]})
        data["history"].append({"role": "model", "parts": [text]})
        data["last_story"] = text
        db[cid] = data
        save_db(db)
        return text
    except Exception as e:
        return f"⚠️ Error AI: {str(e)}"

# ==========================================
# 5. HANDLERS (START & MC SETUP)
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    msg = bot.send_message(message.chat.id, "🌟 <b>ROMKOM V.60</b>\n\nMasukkan <b>Nama Karakter Utamamu</b>:", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_mc_name)

def process_mc_name(message):
    name = message.text.strip()
    msg = bot.send_message(message.chat.id, f"Sebutkan <b>Detail/Sifat/Fisik</b> {name}:", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_mc_desc, name)

def process_mc_desc(message, name):
    desc = message.text.strip()
    db = load_db()
    cid = str(message.chat.id)
    db[cid] = {"mc": {"name": name, "desc": desc}, "characters": [], "history": [], "last_story": ""}
    save_db(db)
    bot.send_message(message.chat.id, f"✅ MC <b>{name}</b> Tersimpan!", parse_mode="HTML", reply_markup=get_main_menu())

# ==========================================
# 6. TAMBAH KARAKTER NPC
# ==========================================
@bot.message_handler(func=lambda m: m.text == "👤 Tambah Karakter")
def cmd_add_char(message):
    msg = bot.send_message(message.chat.id, "Nama karakter baru:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_npc_name)

def process_npc_name(message):
    name = message.text.strip()
    msg = bot.send_message(message.chat.id, f"Detail/Sifat untuk <b>{name}</b>:", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_npc_desc, name)

def process_npc_desc(message, name):
    desc = message.text.strip()
    db = load_db()
    cid = str(message.chat.id)
    db[cid]["characters"].append({"name": name, "desc": desc})
    save_db(db)
    bot.send_message(message.chat.id, f"✅ Karakter <b>{name}</b> ditambahkan!", parse_mode="HTML", reply_markup=get_main_menu())

# ==========================================
# 7. CALLBACKS (INTERAKSI & REGEN)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    data = get_user_data(chat_id)
    bot.answer_callback_query(call.id)

    if call.data == "act_regen":
        bot.send_message(chat_id, "🔄 <i>Mengulang respon terakhir...</i>", parse_mode="HTML")
        # Ambil prompt user terakhir dari history sebelum dihapus
        last_prompt = data['history'][-2]['parts'][0] if len(data['history']) >= 2 else "Lanjutkan ceritanya."
        story = generate_ai_response(chat_id, last_prompt, is_regen=True)
        bot.send_message(chat_id, story, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))

    elif call.data == "act_mc":
        msg = bot.send_message(chat_id, f"Aksi {data['mc']['name']}:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_story_step, f"{data['mc']['name']} melakukan:")

    elif call.data.startswith("act_char_"):
        idx = int(call.data.split("_")[-1])
        name = data['characters'][idx]['name']
        msg = bot.send_message(chat_id, f"Aksi {name}:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_story_step, f"{name} melakukan:")

    elif call.data == "act_auto":
        bot.send_message(chat_id, "⏩ <i>Melanjutkan otomatis (2 Paragraf)...</i>", parse_mode="HTML")
        story = generate_ai_response(chat_id, "Lanjutkan cerita ini secara detail dan puitis dalam 2 paragraf.")
        bot.send_message(chat_id, story, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))

    elif call.data == "act_narrator":
        msg = bot.send_message(chat_id, "Narasi berikutnya:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_story_step, "Narator:")

def process_story_step(message, prefix):
    chat_id = message.chat.id
    bot.send_message(chat_id, "⏳ <i>AI Mengetik...</i>", parse_mode="HTML")
    story = generate_ai_response(chat_id, f"{prefix} {message.text}")
    bot.send_message(chat_id, story, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
    bot.send_message(chat_id, "👇 Menu Utama:", reply_markup=get_main_menu())

# ==========================================
# 8. EXPORT, IMPORT, RESET
# ==========================================
@bot.message_handler(func=lambda m: m.text == "💾 Export Cerita")
def cmd_export(message):
    data = get_user_data(message.chat.id)
    if not data['mc']['name']: return
    bio = io.BytesIO(json.dumps(data, indent=4, ensure_ascii=False).encode())
    bio.name = f"story_{message.chat.id}.json"
    bot.send_document(message.chat.id, bio, caption="📂 Backup ceritamu.", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "📂 Import Cerita")
def cmd_import(message):
    msg = bot.send_message(message.chat.id, "Kirim file .json backup:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import)

def process_import(message):
    if not message.document: return
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    db = load_db()
    db[str(message.chat.id)] = json.loads(downloaded.decode())
    save_db(db)
    bot.send_message(message.chat.id, "✅ Berhasil Import!", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "🔄 Reset")
def cmd_reset(message):
    db = load_db()
    db.pop(str(message.chat.id), None)
    save_db(db)
    bot.send_message(message.chat.id, "🔄 Data Dihapus. Klik /start.", reply_markup=ReplyKeyboardRemove())

# ==========================================
# RUN
# ==========================================
if __name__ == "__main__":
    bot.set_my_commands([BotCommand("start", "Mulai"), BotCommand("reset", "Reset")])
    bot.infinity_polling()
