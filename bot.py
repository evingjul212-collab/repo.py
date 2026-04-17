import os
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)

# =========================
# ENV
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# =========================
# MEMORY USER
# =========================
user_memory = {}

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo! 🤖\nKirim pesan apa saja untuk ngobrol dengan AI (Gemini)."
    )

# =========================
# RESET MEMORY
# =========================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_memory[user_id] = []
    await update.message.reply_text("Memory kamu sudah direset 🧠")

# =========================
# GEMINI FUNCTION (ANTI ERROR)
# =========================
def ask_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()

        print("DEBUG:", data)  # penting buat Railway log

        # Aman dari crash
        if "candidates" in data and len(data["candidates"]) > 0:
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except:
                return "⚠️ Format response aneh dari Gemini"
        else:
            return "❌ Error Gemini:\n" + str(data)

    except Exception as e:
        print("ERROR:", e)
        return "⚠️ Server error, coba lagi nanti"

# =========================
# HANDLE CHAT
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    if user_id not in user_memory:
        user_memory[user_id] = []

    # Simpan history (max 6 biar ringan)
    user_memory[user_id].append(user_text)
    history = user_memory[user_id][-6:]

    prompt = "Jawab dengan santai dan jelas:\n" + "\n".join(history)

    reply = ask_gemini(prompt)

    # simpan balasan juga
    user_memory[user_id].append(reply)

    await update.message.reply_text(reply)

# =========================
# MAIN
# =========================
def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("❌ ENV belum di set!")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 BOT GEMINI RUNNING...")
    app.run_polling()

# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()
