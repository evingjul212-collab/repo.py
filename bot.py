import os
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_romcom(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=f"Cerita romcom lucu: {prompt}"
        )

        try:
            return response.text
        except:
            return "⚠️ AI error"

    except Exception as e:
        return f"❌ {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💖 Kirim ide romcom!")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Proses...")

    story = generate_romcom(update.message.text)
    await update.message.reply_text(story[:3500])

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("BOT HIDUP 🚀")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
