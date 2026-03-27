import os
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN belum di set")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY belum di set")

# Setup Gemini baru
client = genai.Client(api_key=GEMINI_API_KEY)

# Generator cerita
def generate_romcom(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=f"""
Buat cerita ROMCOM lucu, ringan, banyak dialog.
Gaya Gen Z Indonesia, ending happy.

Ide: {prompt}

Format:
Judul:
Karakter:
Cerita:
"""
        )

        return response.text if response.text else "⚠️ AI tidak merespon"

    except Exception as e:
        return f"❌ Error AI: {str(e)}"

# Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💖 Kirim ide romcom!")

# Handle
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Lagi bikin cerita...")

    story = generate_romcom(update.message.text)

    if len(story) > 3500:
        story = story[:3500] + "\n\n...(dipotong)"

    await update.message.reply_text(story)

# Main
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
