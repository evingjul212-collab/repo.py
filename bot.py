import os
import telebot
import google.generativeai as genai
import time

# 1. SETTING DATA (AMBIL DARI RAILWAY VARIABLES)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

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

model = genai.GenerativeModel(model_siap)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- TEMPAT PENYIMPANAN INGATAN (HISTORY) ---
# Disimpan per orang biar ceritanya nggak ketuker sama user lain
sesi_chat = {}

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

# 3. HANDLER UTAMA (UNTUK CHAT BIASA)
@bot.message_handler(func=lambda message: True)
def handle_obrolan(message):
    user_id = message.from_user.id
    teks_masuk = message.text.lower()

    # Jika user ketik manual "baru" atau "ulang", kita reset juga
    if teks_masuk in ['baru', 'reset', 'ulang', 'clear']:
        if user_id in sesi_chat:
            del sesi_chat[user_id]
        bot.reply_to(message, "🧹 **Selesai!** Ingatan dibersihkan. Mau bikin cerita apa kita sekarang?")
        return

    try:
        print(f"User {user_id}: {message.text}")

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

        # KIRIM BALASAN KE TELEGRAM
        if response and response.text:
            # Telegram maksimal 4096 karakter, kita potong dikit biar aman
            bot.reply_to(message, response.text[:4000])
        else:
            bot.reply_to(message, "⚠️ Google lagi bengong, coba ketik lagi Boss!")

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

# 4. JALANKAN BOT
if __name__ == "__main__":
    print("🧹 Membersihkan jalur lama...")
    bot.remove_webhook()
    time.sleep(1)
    print(f"🚀 BOT JALAN PAKAI MODEL: {model_siap}")
    bot.infinity_polling(skip_pending=True)
