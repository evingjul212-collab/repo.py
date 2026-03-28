import os
import sqlite3
import json
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PATH = '/data/story_bot.db' if os.path.exists('/data') else 'story_bot.db'

# Setup Groq
client = Groq(api_key=GROQ_API_KEY)
MODEL_NAME = "llama-3.3-70b-specdec" # Model Llama terbaru yang sangat pintar

# --- DATABASE LOGIC (Sama seperti sebelumnya) ---
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
    return (json.loads(row[0]), row[1]) if row else ([], "Umum")

def save_user_data(user_id, history, genre):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, chat_history, genre) VALUES (?, ?, ?)",
              (user_id, json.dumps(history), genre))
    conn.commit()
    conn.close()

# --- LOGIKA CERITA GROQ ---

async def jalankan_logika_cerita(update: Update, context: ContextTypes.DEFAULT_TYPE, teks_input: str):
    user_id = update.effective_user.id
    history, genre = get_user_data(user_id)
    chat_id = update.effective_chat.id
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Siapkan pesan untuk Groq (Formatnya mirip ChatGPT)
        messages = [
            {"role": "system", "content": f"Kamu penulis cerita {genre} profesional. Gunakan Bahasa Indonesia. "
                                          "JANGAN tambah karakter baru tanpa izin. Di akhir, berikan Opsi A dan B."}
        ]
        
        # Tambahkan history (Ambil 8 turn terakhir saja agar hemat)
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["parts"][0]})
        
        messages.append({"role": "user", "content": teks_input})

        # Panggil API Groq
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.8,
            max_tokens=1000
        )
        
        response_text = completion.choices[0].message.content

        # Update History
        history.append({"role": "user", "parts": [teks_input]})
        history.append({"role": "assistant", "parts": [response_text]})
        save_user_data(user_id, history[-10:], genre)

        # Tombol
        keyboard = [[InlineKeyboardButton("Opsi A 💡", callback_data="A"),
                     InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
                    [InlineKeyboardButton("Opsi C (Ketik) ✏️", callback_data="C")]]
        
        await context.bot.send_message(chat_id=chat_id, text=response_text, reply_markup=InlineKeyboardMarkup(keyboard))
                
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error Groq: {str(e)}")

# --- HANDLER (start, reset, genre, callback tetap sama) ---
# ... (Gunakan handler yang sudah kita buat sebelumnya di file bot.py) ...

# Salin bagian handler dari kode Gemini sebelumnya ke bawah sini
