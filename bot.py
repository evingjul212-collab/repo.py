import os
import telebot
import google.generativeai as genai

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

print("🔍 Mencari model Gemini...")

model_siap = None

try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print("✔ Model ditemukan:", m.name)
            model_siap = m.name
            break
except Exception as e:
    print("❌ Gagal ambil model:", e)

if not model_siap:
    model_siap = "gemini-1.5-flash"

print("🚀 Pakai model:", model_siap)

model = genai.GenerativeModel(model_siap)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle(message):
    try:
        print("User:", message.text)

        response = model.generate_content(
            f"Buat cerita romcom lucu Indonesia: {message.text}"
        )

        if not response or not response.text:
            bot.reply_to(message, "⚠️ AI lagi sibuk, coba lagi...")
            return

        bot.reply_to(message, response.text[:3500])

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

print("✅ BOT JALAN...")
bot.infinity_polling()
