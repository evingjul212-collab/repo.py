import os
import requests
import base64
import time
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

SYSTEM_PROMPT = """Kamu adalah AI assistant pintar.
- Jawaban jelas & santai
- Jago coding Python
- Bisa debug error
- Jelaskan step-by-step"""

# =========================
# MEMORY
# =========================
user_memory = {}

# =========================
# SPLIT TELEGRAM MESSAGE
# =========================
def split_text(text, max_length=4000):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

async def send_long_message(update, text):
    parts = split_text(text)
    for part in parts:
        await update.message.reply_text(part)

# =========================
# GEMINI TEXT
# =========================
def ask_gemini(messages):
    for MODEL in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": messages,
            "generationConfig": {
                "maxOutputTokens": 1000
            }
        }

        try:
            res = requests.post(url, json=payload, timeout=30)
            data = res.json()

            print(f"[TEXT {MODEL}]:", data)

            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]

        except Exception as e:
            print("ERROR:", e)

    return "❌ Semua model gagal"

# =========================
# GEMINI IMAGE
# =========================
def ask_gemini_image(prompt, image_data):
    for MODEL in MODELS:
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
            ],
            "generationConfig": {
                "maxOutputTokens": 1000
            }
        }

        for attempt in range(2):
            try:
                res = requests.post(url, json=payload, timeout=30)
                data = res.json()

                print(f"[IMAGE {MODEL} attempt {attempt}]:", data)

                if "candidates" in data and len(data["candidates"]) > 0:
                    return data["candidates"][0]["content"]["parts"][0]["text"]

                if "error" in data and data["error"]["code"] == 503:
                    time.sleep(2)
                    continue

            except Exception as e:
                print("ERROR:", e)

    return "❌ Gagal proses gambar (server sibuk)"

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI Assistant siap!\n\n"
        "✔ Chat\n✔ Coding Python\n✔ Baca gambar\n\n"
        "/reset untuk reset memory"
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

    await send_long_message(update, reply)

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

    prompt = "Jelaskan gambar ini dengan detail"

    reply = ask_gemini_image(prompt, image_data)

    await send_long_message(update, reply)

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

    print("🚀 BOT READY (FULL AI)")
    app.run_polling()

# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()
