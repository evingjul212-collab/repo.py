import os
import sqlite3
import json
import logging
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PATH = '/data/story_bot.db' if os.path.exists('/data') else 'story_bot.db'

# Inisialisasi Groq
client = Groq(api_key=GROQ_API_KEY)
# Model Llama 3.3 70B adalah yang terpintar dan tercepat di Groq saat ini
MODEL_NAME = "llama-3.3-70b-specdec"

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

# --- LOGIKA CERITA (MESIN GROQ) ---

def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

async def jalankan_logika_cerita(update: Update, context: ContextTypes.DEFAULT_TYPE, teks_input: str):
    user_id = update.effective_user.id
    history, genre = get_user_data(user_id)
    chat_id = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Format pesan untuk Groq (System -> History -> User)
        messages = [
            {
                "role": "system", 
                "content": (
                    f"Kamu adalah penulis cerita interaktif profesional dengan genre {genre}. "
                    "Gunakan Bahasa Indonesia yang menarik. JANGAN menambah karakter baru tanpa izin. "
                    "Tulis kelanjutan cerita secara logis. DI AKHIR PESAN, WAJIB BERIKAN: "
                    "Opsi A: [pilihan alur 1], Opsi B: [pilihan alur 2]."
                )
            }
        ]
        
        # Masukkan history (Ambil 6 turn terakhir agar hemat token dan memori)
        for h in history[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
        
        # Masukkan input user terbaru
        messages.append({"role": "user", "content": teks_input})

        # Panggil API Groq
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.8,
            max_tokens=1000
        )
        
        response_text = completion.choices[0].message.content

        # Update History di Database
        history.append({"role": "user", "content": teks_input})
        history.append({"role": "assistant", "content": response_text})
        save_user_data(user_id, history[-10:], genre)

        # Siapkan Tombol
        keyboard = [
            [InlineKeyboardButton("Opsi A 💡", callback_data="A"),
             InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
            [InlineKeyboardButton("Opsi C (Ketik Sendiri) ✏️", callback_data="C")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Kirim pesan
        parts = split_text(response_text)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await context.bot.send_message(chat_id=chat_id, text=part, reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=part)
                
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error Groq: {str(e)}")

# --- HANDLER BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **Selamat Datang di Story Bot (Powered by Groq)!**\n\n"
        "Gunakan `/genre` untuk pilih tema, atau langsung ketik awal ceritanya.\n"
        "Gunakan `/reset` jika ingin menghapus ingatan bot."
    )

async def set_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Horor 👻", callback_data="g_Horor"),
         InlineKeyboardButton("Fantasi 🧙", callback_data="g_Fantasi")],
        [InlineKeyboardButton("Sci-Fi 🚀", callback_data="g_Sci-Fi"),
         InlineKeyboardButton("Romance ❤️", callback_data="g_Romance")]
    ]
    await update.message.reply_text("Pilih Genre Ceritamu:", reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_user_data(user_id, [], "Umum")
    await update.message.reply_text("🧹 **Ingatan dihapus!** Silahkan mulai cerita baru.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await jalankan_logika_cerita(update, context, update.message.text)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data.startswith("g_"):
        new_genre = data.split("_")[1]
        history, _ = get_user_data(user_id)
        save_user_data(user_id, history, new_genre)
        await query.edit_message_text(f"✅ Genre diubah ke: **{new_genre}**.")
    
    elif data == "C":
        await query.message.reply_text("Silahkan ketik alur ceritamu sendiri (Opsi C) sekarang!")
    
    else:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Mem
