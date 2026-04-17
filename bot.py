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

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Memory sederhana
user_memory = {}

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo! 🤖\nKirim pesan apa saja untuk ngobrol dengan Gemini AI."
    )

# =========================
# RESET
# =========================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_memory[user_id] = []
    await update.message.reply_text("Memory direset 🧠")

# =========================
# CHAT HANDLER
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    if user_id not in user_memory:
        user_memory[user_id] = []

    # Simpan user message
    user_memory[user_id].append(user_text)

    # Ambil 5 terakhir biar ringan
    history = user_memory[user_id][-5:]

    prompt = "\n".join(history)

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

        response = requests.post(
            url,
            json={
                "contents": [
                    {
                        "parts": [{"text": prompt}]
                    }
                ]
            },
            timeout=30
        )

        data = response.json()

        reply = data["candidates"][0]["content"]["parts"][0]["text"]

        # Simpan jawaban
        user_memory[user_id].append(reply)

        await update.message.reply_text(reply)

    except Exception as e:
        print(e)
        await update.message.reply_text("Error bro 😅 cek API / quota")

# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("BOT GEMINI RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
