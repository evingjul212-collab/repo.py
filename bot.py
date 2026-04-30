import os
import json
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
import google.generativeai as genai
from groq import Groq
import io

# ==========================================
# KODE: ROMKOM ENGINE V.32.3 - ROLEPLAY OPTIMIZED
# Deskripsi: 70% DIALOG, 30% NARASI, FIXED IMPORT
# ==========================================

# --- CONFIG ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

genai.configure(api_key=GEMINI_KEY)
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
bot = telebot.TeleBot(BOT_TOKEN)

DB_FILE = "experimental_db.json"

# Instruksi Dasar dengan Rasio Dialog/Narasi
SYSTEM_INSTRUCTION = """Kamu AI GM RomCom 21+. RESPON WAJIB 2 PARAGRAF. Gaya Indonesia kasual, sensual, puitis. 
ATURAN FORMAT:
1. Jika Karakter beraksi: Wajib 70% Dialog interaksi dan 30% Narasi situasi/tindakan.
2. Jika Narator beraksi: Wajib 100% Narasi suasana, situasi, dan perasaan tanpa dialog.
3. Gunakan tanda kutip "..." untuk setiap percakapan. 
4. ANTI-REPETISI."""

# --- FUNGSI DATA (ASLI & AMAN) ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_db(db):
    with open(DB_FILE, 'w') as f: json.dump(db, f, indent=4)

def serialize_history(history):
    return [{"role": e.role, "parts": [e.parts[0].text]} for e in history if hasattr(e, 'parts')]

# --- UI RENDERER ---
def render_main_menu(chat_id, text, prefix=""):
    db = load_db(); cid = str(chat_id)
    if cid not in db: return
    
    m = InlineKeyboardMarkup()
    curr_m = db[cid].get("current_model", "gemini-2.5-flash")
    
    # 1. Baris Karakter
    chars = db[cid].get("characters", {})
    char_btns = [InlineKeyboardButton(f"🎭 {n}", callback_data=f"select_{n}") for n in chars.keys()]
    for i in range(0, len(char_btns), 2):
        m.row(*char_btns[i:i+2])
        
    # 2. Baris Kontrol
    m.row(InlineKeyboardButton("🎙️ Narator", callback_data="select_Narator"),
          InlineKeyboardButton("➕ Tambah Karakter", callback_data="action_add_char"))
    
    # 3. Baris Navigasi
    m.row(InlineKeyboardButton("▶️ AI Lanjut", callback_data="action_lanjut"), 
          InlineKeyboardButton("🔄 Ulang Narasi", callback_data="retry"))
    
    # 4. Model & Reset
    l_g = "✅ G2.5" if "gemini" in curr_m else "🌟 G2.5"
    l_l = "✅ Llama" if "llama" in curr_m else "🚀 Llama"
    m.row(InlineKeyboardButton(l_g, callback_data="set_g25"),
          InlineKeyboardButton(l_l, callback_data="set_llama"))
    m.add(InlineKeyboardButton("🗑️ Hapus Semua Karakter", callback_data="action_clear_cast"))
    
    model_disp = "Gemini 2.5-Flash" if "gemini" in curr_m else "Llama 3.3-70B"
    footer = f"\n\n---\n🤖 *Model: {model_disp}*"
    
    msg = f"{prefix}\n\n{text}{footer}" if prefix else f"{text}{footer}"
    try:
        bot.send_message(chat_id, msg, reply_markup=m, parse_mode="Markdown")
    except:
        bot.send_message(chat_id, msg, reply_markup=m)

# --- ENGINE (OPTIMIZED PROMPT) ---
def execute_engine(chat_id, user_input, is_retry=False):
    cid = str(chat_id); db = load_db()
    bot.send_chat_action(cid, 'typing')
    
    if not isinstance(db[cid].get("history"), list):
        db[cid]["history"] = []
    
    m_now = db[cid].get("current_model", "gemini-2.5-flash")
    if is_retry and len(db[cid]["history"]) >= 1:
        db[cid]["history"].pop()
    
    prompt = db[cid].get("last_input", "Lanjutkan narasinya.") if is_retry else user_input
    db[cid]["last_input"] = prompt

    # Injeksi Profil Karakter
    char_data = db[cid].get("characters", {})
    profiles = "\n\nKONSISTENSI KARAKTER:\n"
    for n, d in char_data.items():
        if isinstance(d, dict):
            profiles += f"- {n}: {d.get('bio','-')}. Sifat: {d.get('sifat','-')}. Kebiasaan: {d.get('habit','-')}\n"
    
    # Deteksi Role Aktif
    active_char = db[cid].get("active_char", "Narator")
    if active_char == "Narator":
        role_instr = "\nFOKUS: Kamu adalah Narator. Berikan narasi 100% suasana dan situasi tanpa dialog."
    else:
        role_instr = f"\nFOKUS: Kamu adalah {active_char}. Berikan 70% dialog percakapan dan 30% narasi tindakan."

    final_instr = SYSTEM_INSTRUCTION + profiles + role_instr

    try:
        model = genai.GenerativeModel(model_name=m_now, system_instruction=final_instr)
        chat = model.start_chat(history=db[cid]["history"][-12:])
        res_t = chat.send_message(prompt).text
        db[cid]["history"] = serialize_history(chat.history)
        save_db(db)
        render_main_menu(cid, res_t)
    except Exception as e:
        render_main_menu(cid, f"⚠️ Error: {str(e)}", prefix="❌ **FAILURE**")

# --- HANDLERS ---
@bot.message_handler(commands=['start', 'new', 'reset'])
def welcome(message):
    cid = str(message.chat.id); db = load_db()
    db[cid] = {"history": [], "current_model": "gemini-2.5-flash", "characters": {}, "step": "playing"}
    save_db(db)
    bot.send_message(cid, "🎮 **ROMKOM ENGINE V.32.3**\nKetik Premis Awal Cerita:")

@bot.message_handler(commands=['import'])
def cmd_import(message):
    cid = str(message.chat.id); db = load_db()
    db[cid]["step"] = "waiting_file"; save_db(db)
    bot.send_message(cid, "📂 **Kirim file JSON kamu!**")

@bot.message_handler(commands=['export'])
def cmd_export(message):
    cid = str(message.chat.id); db = load_db()
    if cid in db:
        bio = io.BytesIO(json.dumps(db[cid], indent=4).encode('utf-8'))
        bio.name = f"story_{cid}.json"
        bot.send_document(cid, bio, caption="💾 Backup Cerita Berhasil.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    cid = str(message.chat.id); db = load_db()
    if db.get(cid, {}).get("step") == "waiting_file":
        try:
            raw = bot.download_file(bot.get_file(message.document.file_id).file_path)
            db[cid] = json.loads(raw); db[cid]["step"] = "playing"; save_db(db)
            last_msg = "📂 **IMPORT SUKSES**\nSila lanjut bercerita."
            if "history" in db[cid]:
                for h in reversed(db[cid]["history"]):
                    if h.get("role") == "model":
                        last_msg = h["parts"][0]; break
            render_main_menu(cid, last_msg)
        except: bot.reply_to(message, "❌ Gagal!")

@bot.message_handler(func=lambda m: True)
def main_text_handler(message):
    cid = str(message.chat.id); db = load_db()
    if cid not in db: return
    step = db[cid].get("step")
    if step == "waiting_file": return

    if step == "add_name":
        db[cid]["temp_char"] = message.text.strip().capitalize()
        db[cid]["step"] = "add_bio"; save_db(db)
        bot.send_message(cid, f"📝 **Relasi {db[cid]['temp_char']}:**")
    elif step == "add_bio":
        db[cid]["temp_bio"] = message.text; db[cid]["step"] = "add_sifat"; save_db(db)
        bot.send_message(cid, "✨ **Sifat:**")
    elif step == "add_sifat":
        db[cid]["temp_sifat"] = message.text; db[cid]["step"] = "add_habit"; save_db(db)
        bot.send_message(cid, "🚬 **Kebiasaan:**")
    elif step == "add_habit":
        name = db[cid].pop("temp_char")
        db[cid]["characters"][name] = {"bio":db[cid].pop("temp_bio"), "sifat":db[cid].pop("temp_sifat"), "habit":message.text}
        db[cid]["step"] = "playing"; save_db(db)
        render_main_menu(cid, f"✅ {name} Siap!")
    elif db[cid].get("waiting_char_input"):
        char = db[cid].get("active_char", "Narator")
        db[cid]["waiting_char_input"] = False; save_db(db)
        execute_engine(cid, f"[{char} melakukan]: {message.text}")
    else:
        execute_engine(cid, message.text)

@bot.callback_query_handler(func=lambda call: True)
def cb_handler(call):
    cid = str(call.message.chat.id); db = load_db()
    if call.data == "retry": execute_engine(cid, "", is_retry=True)
    elif call.data == "action_add_char":
        db[cid]["step"] = "add_name"; save_db(db); bot.send_message(cid, "👤 **Nama Karakter:**")
    elif call.data.startswith("select_"):
        db[cid]["active_char"] = call.data.replace("select_", ""); db[cid]["waiting_char_input"] = True; save_db(db)
        bot.send_message(cid, f"🎭 **Aksi {db[cid]['active_char']}:**")
    elif call.data == "action_lanjut": execute_engine(cid, "Lanjutkan narasi otomatis.")
    elif call.data.startswith("set_"):
        v = call.data.replace("set_", ""); m_map = {"g25":"gemini-2.5-flash", "llama":"llama-3.3-70b-versatile"}
        db[cid]["current_model"] = m_map.get(v); save_db(db); render_main_menu(cid, f"Model ganti: {v}")
    elif call.data == "action_clear_cast":
        db[cid]["characters"] = {}; save_db(db); render_main_menu(cid, "Cast dikosongkan.")

if __name__ == "__main__":
    bot.infinity_polling()
    
