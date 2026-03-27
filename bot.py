import telebot
import google.generativeai as genai
import os

# 1. AMBIL DATA DARI RAILWAY VARIABLES (ATAU ISI MANUAL DI SINI)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7862891281:AAHxxxx_xxxxxxxxxxxxxxx')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyxxxx_xxxxxxxxxxxxxxx')

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# BUKU CATATAN (HISTORY) AGAR BISA "LANJUTKAN"
# Kita simpan per User ID
sesi_chat = {}

@bot.message_handler(func=lambda message: True)
def proses_cerita(message):
    user_id = message.from_user.id
    
    try:
        # Jika belum ada ingatan, buatkan sesi baru
        if user_id not in sesi_chat:
            # Mulai chat dengan instruksi kepribadian penulis Romkom
            sesi_chat[user_id] = model.start_chat(history=[])
            # Pesan pertama kita suntikkan instruksi gaya bahasa
            instruksi = f"Kamu adalah penulis skenario Romantis Komedi pro. Gunakan Bahasa Indonesia yang luwes, puitis, dan lucu. Ide awal: {message.text}"
            response = sesi_chat[user_id].send_message(instruksi)
        else:
            # Jika sudah ada ingatan, tinggal kirim perintah "Lanjutkan" atau ide baru
            response = sesi_chat[user_id].send_message(message.text)
        
        bot.reply_to(message, response.text)
        
    except Exception as e:
        print(f"Error: {e}")
        # Jika error kepenuhan memori, kita reset biar gak macet
        if user_id in sesi_chat:
            del sesi_chat[user_id]
        bot.reply_to(message, "Aduh Boss, Google-nya 'hang' sebentar. Coba ketik ide baru ya!")

# Jalankan Bot
if __name__ == "__main__":
    print("BOT ROMKOM ONLINE DI RAILWAY!")
    bot.infinity_polling()
