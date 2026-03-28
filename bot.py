import os
import sqlite3
import json
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- KONFIGURASI (PASTIKAN DI RAILWAY VARIABLES SUDAH ADA) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PATH = '/data/story_bot.db' if os.path.exists('/data') else 'story_bot.db'

# Inisialisasi Groq - Pakai Model Llama 3.3 Versatile
client = Groq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.3-70b-versatile" 

# --- DATABASE LOGIC ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, chat_history TEXT, genre TEXT)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT chat_history, genre FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]), row[1]
    return [], "Umum"

def save_user_data(user_id, history, genre):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, chat_history, genre) VALUES (?, ?, ?)",
              (user_id, json.dumps(history), genre))
    conn.commit()
    conn.close()

# --- LOGIKA CERITA ---
def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

async def jalankan_logika_cerita(update: Update, context: ContextTypes.DEFAULT_TYPE, teks_input: str):
    user_id = update.effective_user.id
    history, genre = get_user_data(user_id)
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Susun Pesan untuk Groq
        messages = [{"role": "system", "content": f"Kamu penulis cerita {genre} profesional. Gunakan Bahasa Indonesia. JANGAN tambah karakter baru tanpa izin. Di akhir, berikan Opsi A dan B."}]
        for h in history[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": teks_input})

        # Panggil API Groq (Tanpa Streaming biar gak ribet)
        completion = client.chat.completions.create(
            model=MODEL_NAME, 
            messages=messages, 
            temperature=0.8, 
            max_tokens=1000,
            stream=False # <--- Ini kuncinya biar gak error 400
        )
        res = completion.choices[0].message.content

        # Simpan History
        history.append({"role": "user", "content": teks_input})
        history.append({"role": "assistant", "content": res})
        save_user_data(user_id, history[-10:], genre)

        # Tombol Pilihan
        kbd = [[InlineKeyboardButton("Opsi A 💡", callback_data="A"), InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
               [InlineKeyboardButton("Opsi C (Ketik) ✏️", callback_data="C")]]
        
        # Kirim Pesan
        parts = split_text(res)
        for i, part in enumerate(parts):
            m = InlineKeyboardMarkup(kbd) if i == len(parts)-1 else None
            await context.bot.send_message(chat_id=chat_id, text=part, reply_markup=m)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error Mesin: {str(e)}")

# --- HANDLERS ---
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text("📖 **Story Bot Groq Aktif!**\nKetik awal cerita atau pilih `/genre`.")

async def set_genre(u: Update, c: ContextTypes.DEFAULT_TYPE):
    kbd = [[InlineKeyboardButton("Horor 👻", callback_data="g_Horor"), InlineKeyboardButton("Fantasi 🧙", callback_data="g_Fantasi")],
           [InlineKeyboardButton("Sci-Fi 🚀", callback_data="g_Sci-Fi"), InlineKeyboardButton("Romance ❤️", callback_data="g_Romance")]]
    await u.message.reply_text("Pilih Genre Ceritamu:", reply_markup=InlineKeyboardMarkup(kbd))

async def reset_story(u: Update, c: ContextTypes.DEFAULT_TYPE):
    save_user_data(u.effective_user.id, [], "Umum")
    await u.message.reply_text("🧹 **Memori Dihapus!** Silahkan mulai cerita baru.")

async def handle_message(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await jalankan_logika_cerita(u, c, u.message.text)

async def callback_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    if q.data.startswith("g_"):
        new_g = q.data.split("_")[1]
        h, _ = get_user_data(q.from_user.id)
        save_user_data(q.from_user.id, h, new_g)
        await q.edit_message_text(f"✅ Genre sekarang: {new_g}")
    elif q.data == "C":
        await q.message.reply_text("Ketik sendiri kelanjutan ceritamu!")
    else:
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(f"Meneruskan Opsi {q.data}...")
        await jalankan_logika_cerita(u, c, f"Saya pilih Opsi {q.data}. Lanjutkan.")

# --- MAIN ---
if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("genre", set_genre))
    app.add_handler(CommandHandler("reset", reset_story))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("Bot Story Groq Berhasil Jalan!")
    app.run_polling()
