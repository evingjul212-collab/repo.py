import telebot
import google.generativeai as genai

# MASUKKAN TOKEN & KEY MILIKMU
TELEGRAM_TOKEN = '8628912811:AAHqGY3moKiTggiS3lNNg_PogIHurW68dTo'
GEMINI_API_KEY = 'AIzaSyB5i8SrI9t6rkweFZrhuNAMcolnCJ6DCfE'

genai.configure(api_key=GEMINI_API_KEY)

# --- BAGIAN DETEKTIF MODEL ---
print("Sedang mencari daftar model yang tersedia...")
model_siap = ""
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Ketemu model: {m.name}")
            if not model_siap: # Ambil model pertama yang ketemu
                model_siap = m.name
except Exception as e:
    print(f"Gagal mencari model: {e}")

# Pakai model yang baru saja kita temukan
if model_siap:
    print(f"MEMAKAI MODEL: {model_siap}")
    model = genai.GenerativeModel(model_siap)
else:
    print("GAK ADA MODEL KETEMU! Pakai standar saja.")
    model = genai.GenerativeModel('gemini-1.5-flash')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(func=lambda message: True)
def ceritakan(message):
    try:
        print(f"User nanya: {message.text}")
        response = model.generate_content(f"Jawab singkat: {message.text}")
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, f"Aduh, masih error: {str(e)[:100]}")

print("BOT SIAP! Coba chat lagi...")
bot.polling()
