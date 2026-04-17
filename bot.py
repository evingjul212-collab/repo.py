import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "ISI_TOKEN_BOT"
OPENAI_API_KEY = "ISI_API_KEY"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": user_text}]
        }
    )

    result = response.json()
    reply = result["choices"][0]["message"]["content"]

    await update.message.reply_text(reply)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle))

app.run_polling()
