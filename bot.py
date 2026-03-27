import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Ambil dari Railway Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN belum di set")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY belum di set")

# Setup Gemini (MODEL BARU)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Generator cerita
def generate_romcom(prompt):
    full_prompt = f"""
Buat cerita ROMCOM (romantis komedi) yang:
- Lucu, ringan, banyak dialog
- Gaya Gen Z Indonesia
- Ada konflik lucu
- Ending happy

Ide: {prompt}

Format:
Judul:
Karakter:
Cerita:
"""
    response = model.generate_content(full_prompt)
    return response.text

# Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💖 Kirim ide romcom!\n\nContoh:\ncowok dingin jatuh cinta sama cewek cerewet di Bali"
    )

# Handle pesan
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Lagi bikin cerita...")

    try:
        story = generate_romcom(update.message.text)

        # Batasi panjang biar aman
        if len(story) > 3500:
            story = story[:3500] + "\n\n...(dipotong)"

        await update.message.reply_text(story)

    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))

# Run bot
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("✅ Bot jalan...")
app.run_polling()
