import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Generator cerita
def generate_romcom(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Kamu penulis romcom Indonesia lucu, gaya Gen Z."},
                {"role": "user", "content": f"Buat cerita romcom: {prompt}"}
            ],
            max_tokens=800
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Error: {str(e)}"

# Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💖 Kirim ide romcom!")

# Handle
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Lagi bikin cerita...")

    story = generate_romcom(update.message.text)

    if len(story) > 3500:
        story = story[:3500]

    await update.message.reply_text(story)

# Main
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("✅ Bot jalan...")

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
