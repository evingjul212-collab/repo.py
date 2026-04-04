import os
import logging
from google import genai
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# 1. Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 2. Setup Gemini SDK Terbaru
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 3. Definisi tahapan percakapan Manual
GENDER, HAIR_STYLE, HAIR_COLOR, CLOTHES, BACKGROUND, RATIO = range(6)

# --- FUNGSI UNTUK IMAGE TO PROMPT ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("Sedang membaca gambar... Tunggu bentar Boss 🔍")
    
    # Ambil foto
    photo_file = await update.message.photo[-1].get_file()
    image_data = await photo_file.download_as_bytearray()
    
    try:
        # Panggil Gemini Vision terbaru
        response = client.models.generate_content(
            model='gemini-2.0-flash', # Pakai model terbaru 2.0
            contents=[
                "Describe this image in detail for an AI image generator prompt. Use English, focus on subject, lighting, and style.",
                bytes(image_data)
            ]
        )
        await status_msg.edit_text(f"✅ **Hasil Prompt dari Foto:**\n\n`{response.text}`", parse_mode="Markdown")
    except Exception as e:
        await status_msg.edit_text(f"Waduh error Boss: {e}")

# --- FUNGSI UNTUK MANUAL PROMPT GENERATOR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Laki-laki", "Perempuan"]]
    await update.message.reply_text(
        "Halo Boss! Kirim FOTO untuk buat prompt otomatis, atau ketik /buat untuk buat manual.\n\nApa gender subyeknya?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("Gaya rambutnya? (contoh: Undercut, Long wavy, Bald)", reply_markup=ReplyKeyboardRemove())
    return HAIR_STYLE

async def get_hair_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_style'] = update.message.text
    await update.message.reply_text("Warna rambutnya?")
    return HAIR_COLOR

async def get_hair_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_color'] = update.message.text
    await update.message.reply_text("Pakai baju apa?")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['clothes'] = update.message.text
    await update.message.reply_text("Latar belakangnya di mana?")
    return BACKGROUND

async def get_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['background'] = update.message.text
    reply_keyboard = [["1:1", "16:9", "9:16"]]
    await update.message.reply_text("Pilih Ratio:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return RATIO

async def generate_manual_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ratio'] = update.message.text
    u = context.user_data
    final = (f"A professional photo of a {u['gender']} with {u['hair_color']} {u['hair_style']} hair, "
             f"wearing {u['clothes']}, standing in {u['background']}, 8k, cinematic --ar {u['ratio']}")
    await update.message.reply_text(f"✅ **Prompt Manual:**\n\n`{final}`", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token: return

    application = Application.builder().token(token).build()

    # Handler untuk Gambar (Otomatis)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))

    # Handler untuk Chat (Manual)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CommandHandler("buat", start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HAIR_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair_style)],
            HAIR_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair_color)],
            CLOTHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_clothes)],
            BACKGROUND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_background)],
            RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_manual_prompt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()
