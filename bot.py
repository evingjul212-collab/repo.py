import os
import sqlite3
import json
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
    model_name="gemini-1.5-flash",
    system_instruction=(
        "Kamu adalah penulis cerita interaktif. Gunakan Bahasa Indonesia yang seru. "
        "Tugasmu: Lanjutkan cerita berdasarkan input user dan genre yang dipilih. "
        "WAJIB: Di akhir pesan, berikan Opsi A dan Opsi B yang menarik. "
        "Ingatkan user mereka bisa pakai Opsi C dengan mengetik langsung."
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_history, genre FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]), row[1]
    return [], "Umum"

def save_user_data(user_id, history, genre):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, chat_history, genre) VALUES (?, ?, ?)",
              (user_id, json.dumps(history), genre))
    conn.commit()
    conn.close()

# --- HANDLER ---

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
    user_id = update.effective_user.id
    user_input = update.message.text
    history, genre = get_user_data(user_id)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        prompt = f"[Genre: {genre}] {user_input}"
        chat = model.start_chat(history=history)
        response = chat.send_message(prompt)
        
        # Simpan History (Maksimal 12 pesan agar tidak berat)
        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [content.parts[0].text]})
        save_user_data(user_id, new_history[-12:], genre)

        # Tombol A, B, C
        keyboard = [
            [InlineKeyboardButton("Opsi A 💡", callback_data="A"),
             InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
            [InlineKeyboardButton("Opsi C (Ketik Sendiri) ✏️", callback_data="C")]
        ]
        
        # Split text jika kepanjangan (>4000 char)
        text = response.text
        if len(text) > 4000:
            await update.message.reply_text(text[:4000])
            await update.message.reply_text(text[4000:], reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

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
        await query.message.reply_text("Silahkan ketik alur ceritamu sendiri sekarang!")
    
    else:
        # User pilih A atau B
        await query.message.reply_text(f"Meneruskan Opsi {data}...")
        # Manipulasi update object untuk panggil handle_message
        query.message.text = f"Saya pilih Opsi {data}. Lanjutkan."
        update.message = query.message
        await handle_message(update, context)

if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("genre", set_genre))
    app.add_handler(CommandHandler("reset", reset_story))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling()
