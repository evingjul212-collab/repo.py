import os
import sqlite3
import json
import logging
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- KONFIGURASI RAILWAY ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Folder /data adalah Mount Path dari Railway Volume
DB_PATH = '/data/story_bot.db' if os.path.exists('/data') else 'story_bot.db'

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", # Gunakan versi stabil
    system_instruction=(
        "Kamu adalah penulis cerita interaktif profesional. Gunakan Bahasa Indonesia yang seru. "
        "Tugasmu: Lanjutkan cerita berdasarkan input user dan genre yang dipilih. "
        "WAJIB: Di akhir pesan, berikan Opsi A dan Opsi B yang sangat spesifik terhadap alur. "
        "Beritahu user mereka bisa pakai Opsi C dengan cara mengetik langsung alur yang mereka inginkan."
    )
)

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

# --- LOGIKA CERITA (MESIN UTAMA) ---

def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

async def jalankan_logika_cerita(update: Update, context: ContextTypes.DEFAULT_TYPE, teks_input: str):
    """Fungsi tunggal untuk memproses cerita dari input mana pun (tombol/ketik)"""
    user_id = update.effective_user.id
    history, genre = get_user_data(user_id)
    
    # Gunakan target pesan yang benar (balas pesan terakhir atau query)
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        prompt = f"[Genre: {genre}] {teks_input}"
        chat = model.start_chat(history=history)
        response = chat.send_message(prompt)
        
        # Simpan History (Maksimal 12 turn agar tidak lemot)
        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [content.parts[0].text]})
        save_user_data(user_id, new_history[-12:], genre)

        # Siapkan Tombol
        keyboard = [
            [InlineKeyboardButton("Opsi A 💡", callback_data="A"),
             InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
            [InlineKeyboardButton("Opsi C (Ketik Sendiri) ✏️", callback_data="C")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Kirim hasil ke user
        parts = split_text(response.text)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await context.bot.send_message(chat_id=chat_id, text=part, reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=chat_id, text=part)
                
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Terjadi kesalahan: {str(e)}")

# --- HANDLER PERINTAH & PESAN ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **Selamat Datang di Story Bot!**\n\n"
        "Gunakan `/genre` untuk pilih tema, atau langsung ketik awal ceritanya.\n"
        "Gunakan `/reset` jika ingin menghapus ingatan bot dan mulai baru."
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
    # Langsung teruskan teks yang diketik user ke mesin cerita
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
        await query.edit_message_text(f"✅ Genre diubah ke: **{new_genre}**. Silahkan lanjut bercerita!")
    
    elif data == "C":
        await query.message.reply_text("Silahkan ketik alur ceritamu sendiri (Opsi C) sekarang!")
    
    else:
        # Hapus tombol agar tidak diklik ulang
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Kamu memilih: *Opsi {data}*", parse_mode="Markdown")
        
        # Kirim pilihan sebagai input teks ke mesin cerita
        await jalankan_logika_cerita(update, context, f"Saya pilih Opsi {data}. Lanjutkan ceritanya.")

# --- MAIN ---

if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("genre", set_genre))
    app.add_handler(CommandHandler("reset", reset_story))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    print("Bot Story Generator Aktif & Stabil...")
    app.run_polling()
