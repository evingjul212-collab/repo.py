import os
import telebot
import google.generativeai as genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# --- BAGIAN DETEKTIF (BIAR LANCAR) ---
model_siap = "gemini-1.5-flash"
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            model_siap = m.name
            break
except:
    pass

model = genai.GenerativeModel(model_siap)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- FITUR INGATAN (HISTORY) ---
# Kita simpan "buku catatan" per orang biar ceritanya gak ketukar
sesi_chat = {}

@bot.message_handler(func=lambda message: True)
def handle(message):
    user_id = message.from_user.id
    try:
        print(f"User ({user_id}): {message.text}")

        # 1. Jika orang ini baru pertama kali chat, buatkan "Buku Catatan" baru
        if user_id not in sesi_chat:
            sesi_chat[user_id] = model.start_chat(history=[])
            # Kasih instruksi awal biar dia jadi penulis Romkom
            perintah = f"Halo, kamu penulis Romkom lucu Indonesia. Ini ide saya: {message.text}"
        else:
            # 2. Jika sudah ada, tinggal lanjutin (History otomatis terkirim)
            perintah = message.text

        # KIRIM PESAN PAKAI SESI (Bukan generate_content biasa)
        response = sesi_chat[user_id].send_message(perintah)

        if not response or not response.text:
            bot.reply_to(message, "⚠️ Google lagi bengong, coba lagi...")
            return

        bot.reply_to(message, response.text[:3500])

    except Exception as e:
        # Jika error (misal memori kepenuhan), kita reset sesinya
        if user_id in sesi_chat:
            del sesi_chat[user_id]
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

print(f"✅ BOT JALAN PAKAI MODEL: {model_siap}")
bot.infinity_polling(skip_pending=True)
