import telebot
import google.generativeai as genai
import os
import time

# 1. DATA DARI RAILWAY VARIABLES
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Konfigurasi Paksa ke Versi v1 (Bukan v1beta)
genai.configure(api_key=GEMINI_API_KEY, transport='rest')

# Gunakan nama model polosan tanpa embel-embel models/
model_name = 'gemini-1.5-flash' 

# Inisialisasi Model
model = genai.GenerativeModel(model_name)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Buku Catatan History (Sesi Chat)
chat_sessions = {}

@bot.message_handler(func=lambda message: True)
def proses_chat(message):
    user_id = message.from_user.id
    try:
        # Jika belum ada sesi, mulai baru
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
            instruksi = f"Kamu penulis Romkom pro. Gunakan Bahasa Indonesia yang luwes. Ide: {message.text}"
            response = chat_sessions[user_id].send_message(instruksi)
        else:
            # Lanjutkan cerita sebelumnya
            response = chat_sessions[user_id].send_message(message.text)
        
        bot.reply_to(message, response.text)
        
    except Exception as e:
        print(f"Error detail: {e}")
        # Jika error 404/429, kita hapus sesi biar bisa mulai ulang
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        
        # Pesan error yang lebih informatif untuk kamu di Telegram
        if "404" in str(e):
            bot.reply_to(message, "Aduh Boss, Google ganti jalur lagi (404). Tunggu saya 'reconnect' ya!")
        else:
            bot.reply_to(message, "Ada kendala teknis, coba ketik 'Halo' lagi!")

if __name__ == "__main__":
    print("MEMBERSIHKAN JALUR WEBHOOK...")
    bot.remove_webhook()
    time.sleep(1)
    print(f"BOT ROMKOM ONLINE PAKAI MODEL: {model_name}")
    bot.infinity_polling(skip_pending=True)
