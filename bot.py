import os
import telebot
import logging
import sqlite3
import json
import google.generativeai as genai
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# 1. SETTING DATA (AMBIL DARI RAILWAY VARIABLES)
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

# --- BAGIAN DETEKTIF MODEL ---
print("🔍 Mencari model Gemini yang aktif...")
model_siap = "gemini-1.5-flash" # Default kalau gagal cari
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            model_siap = m.name
            break
except Exception as e:
    print("❌ Gagal list models, pakai default:", e)
# --- DATABASE SETUP (Agar Tidak Lupa Alur) ---
def init_db():
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (user_id INTEGER PRIMARY KEY, chat_history TEXT)''')
    conn.commit()
    conn.close()

model = genai.GenerativeModel(model_siap)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
def save_history(user_id, history_list):
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    # Simpan sebagai JSON string
    json_history = json.dumps(history_list)
    c.execute("INSERT OR REPLACE INTO history (user_id, chat_history) VALUES (?, ?)", (user_id, json_history))
    conn.commit()
    conn.close()

# --- TEMPAT PENYIMPANAN INGATAN (HISTORY) ---
# Disimpan per orang biar ceritanya nggak ketuker sama user lain
sesi_chat = {}
def load_history(user_id):
    conn = sqlite3.connect('story_bot.db')
    c = conn.cursor()
    c.execute("SELECT chat_history FROM history WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return []

# 2. PERINTAH UNTUK MULAI CERITA BARU (/start atau /reset)
@bot.message_handler(commands=['start', 'reset', 'baru'])
def perintah_reset(message):
    user_id = message.from_user.id
    if user_id in sesi_chat:
        del sesi_chat[user_id] # Bakar catatan lama
    
    sambutan = (
        "✨ **Halo Boss Penulis!** ✨\n\n"
        "Saya sudah siap bikin skenario Romkom lagi.\n"
        "Ingatan saya sudah **KOSONG**. Silakan kasih ide cerita baru!\n\n"
        "💡 *Tips: Kalau mau lanjutin cerita, langsung chat aja.*"
    )
    bot.reply_to(message, sambutan, parse_mode="Markdown")
# --- FUNGSI UTAMA ---

# 3. HANDLER UTAMA (UNTUK CHAT BIASA)
@bot.message_handler(func=lambda message: True)
def handle_obrolan(message):
    user_id = message.from_user.id
    teks_masuk = message.text.lower()
def split_text(text, limit=4000):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

    # Jika user ketik manual "baru" atau "ulang", kita reset juga
    if teks_masuk in ['baru', 'reset', 'ulang', 'clear']:
        if user_id in sesi_chat:
            del sesi_chat[user_id]
        bot.reply_to(message, "🧹 **Selesai!** Ingatan dibersihkan. Mau bikin cerita apa kita sekarang?")
        return
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
        print(f"User {user_id}: {message.text}")
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

        # LOGIKA INGATAN:
        # Jika belum ada buku catatan, buat baru
        if user_id not in sesi_chat:
            sesi_chat[user_id] = model.start_chat(history=[])
            prompt_awal = (
                "Kamu adalah penulis skenario Romantis Komedi (Romkom) Indonesia yang pro. "
                "Gunakan gaya bahasa yang luwes, kocak, dan puitis. "
                "Ide cerita dari saya: " + message.text
            )
            # Kirim pesan pertama
            response = sesi_chat[user_id].send_message(prompt_awal)
        else:
            # Jika sudah ada, tinggal kirim teks lanjutannya
            response = sesi_chat[user_id].send_message(message.text)
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

        # KIRIM BALASAN KE TELEGRAM
        if response and response.text:
            # Telegram maksimal 4096 karakter, kita potong dikit biar aman
            bot.reply_to(message, response.text[:4000])
        else:
            bot.reply_to(message, "⚠️ Google lagi bengong, coba ketik lagi Boss!")
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

    except Exception as e:
        # Jika error (misal limit 429), kita reset sesinya biar gak macet
        print(f"ERROR: {e}")
        if user_id in sesi_chat:
            del sesi_chat[user_id]
        
        error_msg = str(e)
        if "429" in error_msg:
            bot.reply_to(message, "⏳ Wah, Google lagi capek (Limit 429). Tunggu 1 menit ya!")
        else:
            bot.reply_to(message, "❌ Ada kendala teknis. Coba ketik /reset dulu Boss.")
# --- JALANKAN BOT ---

# 4. JALANKAN BOT
if __name__ == "__main__":
    print("🧹 Membersihkan jalur lama...")
    bot.remove_webhook()
    time.sleep(1)
    print(f"🚀 BOT JALAN PAKAI MODEL: {model_siap}")
    bot.infinity_polling(skip_pending=True)
    init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_story))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot Story Generator Aktif...")
    application.run_polling()
