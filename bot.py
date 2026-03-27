import telebot
from google import genai
import os
import time

# 1. DATA DARI RAILWAY VARIABLES
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Inisialisasi Google GenAI Terbaru
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Buku Catatan History per User
chat_sessions = {}

@bot.message_handler(func=lambda message: True)
def proses_chat(message):
    user_id = message.from_user.id
    try:
        # Jika belum ada ingatan, buatkan sesi baru
        if user_id not in chat_sessions:
            chat_sessions[user_id] = client.chats.create(model="gemini-1.5-flash")
            prompt = f"Kamu penulis Romkom pro. Gunakan Bahasa Indonesia yang luwes dan puitis. Ide: {message.text}"
        else:
            prompt = message.text
        
        # Kirim pesan (Cara Baru)
        response = chat_sessions[user_id].send_message(prompt)
        
        bot.reply_to(message, response.text)
        
    except Exception as e:
        print(f"Error detail: {e}")
        # Jika error model/limit, coba reset sesi
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        bot.reply_to(message, "Google lagi update sistem, coba chat 'Halo' lagi ya Boss!")

if __name__ == "__main__":
    print("MEMBERSIHKAN JALUR...")
    bot.remove_webhook()
    time.sleep(1)
    print("BOT ROMKOM (GEN-AI 2.0) ONLINE DI RAILWAY!")
    bot.infinity_polling(skip_pending=True)
