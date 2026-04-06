import os, json, telebot, io
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from google import genai
from google.genai import types

# --- CONFIG ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY)
bot = telebot.TeleBot(BOT_TOKEN)
DB_FILE = "experimental_db.json"
SYSTEM_INSTRUCTION = "Kamu AI GM RomCom 21+. RESPON WAJIB 2 PARAGRAF. Gaya Indonesia kasual, sensual, puitis. ANTI-REPETISI."

# --- DB HANDLER ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_data(chat_id):
    db = load_db()
    cid = str(chat_id)
    if cid not in db:
        db[cid] = {"mc": {"name": "", "desc": ""}, "characters": [], "history": [], "last_story": "", "summary": ""}
        save_db(db)
    return db[cid]

# --- UI GENERATOR ---
def get_main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("➕ Cerita Baru"), KeyboardButton("📂 Import Cerita"))
    markup.add(KeyboardButton("👤 Tambah Karakter"), KeyboardButton("💾 Export Cerita"))
    markup.add(KeyboardButton("🔄 Reset"))
    return markup

def get_interactive_menu(chat_id):
    data = get_user_data(chat_id)
    markup = InlineKeyboardMarkup(row_width=2)
    if data['mc']['name']: markup.add(InlineKeyboardButton(f"🗣 {data['mc']['name']}", callback_data="act_mc"))
    for idx, char in enumerate(data['characters']):
        markup.add(InlineKeyboardButton(f"👤 {char['name']}", callback_data=f"act_char_{idx}"))
    markup.add(InlineKeyboardButton("⏩ Lanjut Otomatis", callback_data="act_auto"), InlineKeyboardButton("👁 Narator", callback_data="act_narrator"))
    markup.add(InlineKeyboardButton("🔄 Ulang Respon (Regen)", callback_data="act_regen"))
    return markup

# --- CORE LOGIC ---
def show_current_status(chat_id):
    data = get_user_data(chat_id)
    char_list = ", ".join([c['name'] for c in data['characters']]) if data['characters'] else "-"
    text = (f"📖 <b>STATUS CERITA DIMUAT</b>\n\n"
            f"<b>MC:</b> {data['mc']['name']} ({data['mc']['desc']})\n"
            f"<b>Tokoh:</b> {char_list}\n"
            f"<b>Alur:</b> {data.get('summary', 'Baru dimulai.')}\n\n"
            f"<b>ADEGAN TERAKHIR:</b>\n{data.get('last_story', 'Silakan mulai cerita baru.')}")
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=get_interactive_menu(chat_id))
    bot.send_message(chat_id, "👇 Pilih aksi atau gunakan menu di bawah:", reply_markup=get_main_menu())

def generate_ai_response(chat_id, prompt, is_regen=False):
    db = load_db(); cid = str(chat_id); data = db[cid]
    if is_regen and len(data['history']) >= 2: data['history'] = data['history'][:-2]
    
    chars_info = "\n".join([f"- {c['name']}: {c['desc']}" for c in data['characters']])
    context = f"MC: {data['mc']['name']} ({data['mc']['desc']})\nNPC:\n{chars_info}\nAlur: {data.get('summary','')}\n"
    
    contents = [types.Content(role=m["role"], parts=[types.Part.from_text(text=m["parts"][0])]) for m in data['history'][-6:]]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=context + "PERINTAH: Tulis 2 paragraf deskriptif. " + prompt)]))

    try:
        res = client.models.generate_content(model="gemini-2.0-flash", contents=contents, config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.9))
        text = res.text
        data["history"].extend([{"role":"user", "parts":[prompt]}, {"role":"model", "parts":[text]}])
        data["last_story"] = text
        if len(data["history"]) % 10 == 0:
            s_res = client.models.generate_content(model="gemini-2.0-flash", contents=[f"Ringkas alur ini jadi 1 paragraf: {text}"])
            data["summary"] = s_res.text
        db[cid] = data; save_db(db)
        return text
    except Exception as e: return f"⚠️ Error: {str(e)}"

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    msg = bot.send_message(message.chat.id, "🌟 <b>ROMKOM V.6.2</b>\nNama MC kamu?", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, lambda m: bot.register_next_step_handler(bot.send_message(m.chat.id, f"Detail/Sifat {m.text}:"), process_mc_final, m.text))

def process_mc_final(message, name):
    db = load_db(); cid = str(message.chat.id)
    db[cid] = {"mc": {"name": name, "desc": message.text}, "characters": [], "history": [], "last_story": "", "summary": ""}
    save_db(db); bot.send_message(message.chat.id, f"✅ MC {name} Siap!", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "👤 Tambah Karakter")
def cmd_add_char(message):
    msg = bot.send_message(message.chat.id, "Nama NPC baru?", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, lambda m: bot.register_next_step_handler(bot.send_message(m.chat.id, f"Detail/Sifat {m.text}:"), process_npc_final, m.text))

def process_npc_final(message, name):
    db = load_db(); cid = str(message.chat.id)
    db[cid]["characters"].append({"name": name, "desc": message.text})
    save_db(db); bot.send_message(message.chat.id, f"✅ {name} masuk!", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "📂 Import Cerita")
def cmd_import(message):
    msg = bot.send_message(message.chat.id, "Kirim file .json backup:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_import)

def process_import(message):
    if not message.document: return bot.send_message(message.chat.id, "Batal.", reply_markup=get_main_menu())
    try:
        data = json.loads(bot.download_file(bot.get_file(message.document.file_id).file_path).decode())
        db = load_db(); db[str(message.chat.id)] = data; save_db(db)
        show_current_status(message.chat.id)
    except: bot.send_message(message.chat.id, "Gagal.", reply_markup=get_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    cid = call.message.chat.id; data = get_user_data(cid); bot.answer_callback_query(call.id)
    if call.data == "act_regen":
        bot.send_message(cid, "🔄 <i>Regenerate...</i>", parse_mode="HTML")
        story = generate_ai_response(cid, data['history'][-2]['parts'][0] if len(data['history'])>=2 else "Lanjut.", True)
        bot.send_message(cid, story, parse_mode="HTML", reply_markup=get_interactive_menu(cid))
    elif call.data == "act_auto":
        story = generate_ai_response(cid, "Lanjutkan cerita secara detail puitis 2 paragraf.")
        bot.send_message(cid, story, parse_mode="HTML", reply_markup=get_interactive_menu(cid))
        bot.send_message(cid, "👇 Menu Utama:", reply_markup=get_main_menu())
    elif call.data == "act_mc":
        msg = bot.send_message(cid, f"Aksi {data['mc']['name']}:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_step, f"{data['mc']['name']}:")

def process_step(message, prefix):
    story = generate_ai_response(message.chat.id, f"{prefix} {message.text}")
    bot.send_message(message.chat.id, story, parse_mode="HTML", reply_markup=get_interactive_menu(message.chat.id))
    bot.send_message(message.chat.id, "👇 Menu Utama:", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "💾 Export Cerita")
def cmd_export(message):
    data = get_user_data(message.chat.id)
    bio = io.BytesIO(json.dumps(data, indent=4, ensure_ascii=False).encode()); bio.name = "story.json"
    bot.send_document(message.chat.id, bio, reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "➕ Cerita Baru")
def cmd_new(message):
    msg = bot.send_message(message.chat.id, "Premis cerita baru?", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, lambda m: bot.send_message(m.chat.id, generate_ai_response(m.chat.id, f"Mulai prolog: {m.text}"), parse_mode="HTML", reply_markup=get_interactive_menu(m.chat.id)))

@bot.message_handler(func=lambda m: m.text == "🔄 Reset")
def cmd_reset(message):
    db = load_db(); db.pop(str(message.chat.id), None); save_db(db)
    bot.send_message(message.chat.id, "Reset berhasil. /start.", reply_markup=ReplyKeyboardRemove())



import time # Tambahkan import time di paling atas

if __name__ == "__main__":
    print("🤖 Mencoba menyalakan mesin...")
    try:
        bot.remove_webhook()
        print("⏳ Menunggu koneksi lama terputus (5 detik)...")
        time.sleep(5) # Kasih jeda biar koneksi lama mati dulu
        
        print("🚀 Bot RomCom V.6.2 Meluncur!")
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=10)
    except Exception as e:
        print(f"❌ Gagal Total: {e}")
