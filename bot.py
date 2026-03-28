import os
import logging
import sqlite3
import json
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- KONFIGURASI ---
# Di Railway, isi ini di bagian "Variables"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=(
        "Kamu adalah penulis cerita interaktif profesional. Gunakan Bahasa Indonesia yang imajinatif. "
        "Tugasmu: Lanjutkan cerita berdasarkan input user. "
        "DI AKHIR SETIAP PESAN, KAMU WAJIB MEMBERIKAN 2 OPSI (Opsi A dan Opsi B). "
        "Beritahu juga user bahwa mereka bisa memilih 'Opsi C' dengan cara mengetik langsung alur cerita yang mereka inginkan."
    )
)

# --- DATABASE SETUP (Agar Tidak Lupa Alur) ---
def init_db():
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (user_id INTEGER PRIMARY KEY, chat_history TEXT)''')
    conn.commit()
    conn.close()

def save_history(user_id, history_list):
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    # Simpan sebagai JSON string
    json_history = json.dumps(history_list)
    c.execute("INSERT OR REPLACE INTO history (user_id, chat_history) VALUES (?, ?)", (user_id, json_history))
    conn.commit()
    conn.close()

def load_history(user_id):
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    c.execute("SELECT chat_history FROM history WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return []

# --- FUNGSI UTAMA ---

def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_history(user_id, []) # Reset history
    await update.message.reply_text(
        "📖 **Selamat Datang di Dunia Cerita!**\n\n"
        "Tuliskan tema cerita (contoh: 'Petualangan di Mars') untuk memulai.\n"
        "Nanti kamu bisa memilih Opsi A/B lewat tombol, atau **Opsi C** dengan cara mengetik alurmu sendiri!"
    )

async def handle_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_input = update.message.text
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Load history dari database
        history = load_history(user_id)
        
        # Mulai chat session dengan history lama
        chat = model.start_chat(history=history)
        response = chat.send_message(user_input)
        
        # Update & Simpan history baru (hanya simpan 10 pesan terakhir agar hemat)
        new_history = []
        for content in chat.history:
            new_history.append({"role": content.role, "parts": [content.parts[0].text]})
        save_history(user_id, new_history[-10:]) 

        # Kirim pesan ke Telegram
        parts = split_text(response.text)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                keyboard = [
                    [InlineKeyboardButton("Opsi A 💡", callback_data="A"),
                     InlineKeyboardButton("Opsi B 🎭", callback_data="B")],
                    [InlineKeyboardButton("Opsi C (Ketik Sendiri) ✏️", callback_data="C")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(part, reply_markup=reply_markup)
            else:
                await update.message.reply_text(part)
                
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    choice = query.data
    
    await query.answer()
    
    if choice == "C":
        await query.message.reply_text("Silahkan **ketik langsung** alur cerita yang kamu inginkan untuk Opsi C!")
    else:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Kamu memilih: *Opsi {choice}*", parse_mode="Markdown")
        # Trigger handle_story dengan teks pilihan
        update.message = query.message
        update.message.text = f"Saya memilih Opsi {choice}. Lanjutkan ceritanya."
        await handle_story(update, context)

# --- JALANKAN BOT ---

if __name__ == "__main__":
    init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot Story Generator Aktif...")
    application.run_polling()
