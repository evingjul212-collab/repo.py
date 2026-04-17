import os
import requests
import base64
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
# CONFIG
# =========================
MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash"
]

SYSTEM_PROMPT = """Kamu adalah AI assistant yang sangat pintar.
Fokus:
- Jawaban jelas, tidak bertele-tele
- Jago coding Python
- Bisa debug error
- Jelaskan step-by-step jika perlu
- Gunakan bahasa santai"""

# =========================
# MEMORY
# =========================
user_memory = {}

# =========================
# GEMINI TEXT
# =========================
def ask_gemini(messages):
    for MODEL in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": messages
        }

        try:
            res = requests.post(url, json=payload, timeout=30)
            data = res.json()

            print(f"[TEXT] {MODEL}:", data)

            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]

        except Exception as e:
            print("ERROR:", e)

    return "❌ Semua model gagal"

# =========================
# GEMINI IMAGE
# =========================
def ask_gemini_image(prompt, image_data):
    MODEL = "gemini-2.5-flash"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_data
                        }
                    }
                ]
            }
        ]
    }

    try:
        res = requests.post(url, json=payload, timeout=30)
        data = res.json()

        print("[IMAGE]:", data)

        if "candidates" in data and len(data["candidates"]) > 0:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return "❌ Error image:\n" + str(data)

    except Exception as e:
        print(e)
        return "⚠️ Error gambar"

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI Assistant siap!\n\n"
        "✔ Chat biasa\n"
        "✔ Bantu coding Python\n"
        "✔ Bisa baca gambar\n\n"
        "/reset untuk hapus memory"
    )

# =========================
# RESET
# =========================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_memory[update.message.from_user.id] = []
    await update.message.reply_text("🧠 Memory direset")

# =========================
# HANDLE TEXT
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if user_id not in user_memory:
        user_memory[user_id] = []

    user_memory[user_id].append({"role": "user", "parts": [{"text": text}]})

    history = user_memory[user_id][-8:]

    messages = [{"role": "user", "parts": [{"text": SYSTEM_PROMPT}]}] + history

    reply = ask_gemini(messages)

    user_memory[user_id].append({"role": "model", "parts": [{"text": reply}]})

    await update.message.reply_text(reply)

# =========================
# HANDLE IMAGE
# =========================
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    path = f"{photo.file_id}.jpg"
    await file.download_to_drive(path)

    with open(path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    prompt = "Analisa gambar ini dan jelaskan secara detail."

    reply = ask_gemini_image(prompt, image_data)

    await update.message.reply_text(reply)

# =========================
# MAIN
# =========================
def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("❌ ENV belum di set")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))

    print("🚀 AI BOT READY (TEXT + IMAGE + CODING)")
    app.run_polling()

if __name__ == "__main__":
    main()
