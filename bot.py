import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN belum di set")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY belum di set")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

def generate_romcom(prompt):
    full_prompt = f"""
Buat cerita ROMCOM lucu, ringan, banyak dialog.
Gaya Gen Z Indonesia, ending happy.

Ide: {prompt}

Format:
Judul:
Karakter:
Cerita:
"""
    response = model.generate_content(full_prompt)
    return response.text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💖 Kirim ide romcom!")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Nulis cerita...")

    try:
        story = generate_romcom(update.message.text)
        await update.message.reply_text(story[:3500])
    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("✅ Bot jalan...")
app.run_polling()  
