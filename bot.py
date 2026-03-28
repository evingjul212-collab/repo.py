import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Ambil dari environment (Railway Variables)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Validasi biar gak error diam-diam
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN belum di set di Variables")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY belum di set di Variables")

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")

# 🎬 Generator ROMCOM
def generate_romcom(prompt):
    full_prompt = f"""
Buat cerita ROMCOM (romantis komedi) yang:
- Lucu, ringan, dan engaging
- Banyak dialog natural
- Gaya Gen Z Indonesia
- Ada konflik lucu
- Ending happy

Ide cerita: {prompt}

Format:
Judul:
Karakter:
Cerita:
"""

    response = model.generate_content(full_prompt)
    return response.text

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💖 Kirim ide cerita romcom!\n\nContoh:\n'cowok dingin jatuh cinta sama cewek cerewet di Bali'"
    )

# handler pesan
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    await update.message.reply_text("⏳ Lagi bikin cerita...")

    try:
        story = generate_romcom(user_input)

        # batasi panjang biar aman di Telegram
        if len(story) > 3500:
            story = story[:3500] + "\n\n...(dipotong)"

        await update.message.reply_text(story)

    except Exception as e:
        await update.message.reply_text("❌ Error: " + str(e))

# main app
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("✅ Bot jalan...")
app.run_polling()
