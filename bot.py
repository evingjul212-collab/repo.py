import os
import logging
import google.generativeai as genai
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# 1. SETUP LOGGING & AI
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Konfigurasi Gemini API (Pastikan GEMINI_API_KEY ada di Railway Variables)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision_model = genai.GenerativeModel('gemini-2.5-flash')

# 2. DEFINISI STATE UNTUK PERCAKAPAN MANUAL
GENDER, HAIR_STYLE, HAIR_COLOR, CLOTHES, BACKGROUND, RATIO = range(6)

# --- FUNGSI IMAGE TO PROMPT (HANDLER FOTO) ---
async def handle_image_to_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Sedang menganalisa gambar... Tunggu sebentar Boss.")
    
    try:
        # Download foto dari Telegram
        photo_file = await update.message.photo[-1].get_file()
        image_data = await photo_file.download_as_bytearray()
        
        # Format input yang benar untuk library google-generativeai terbaru
        content_payload = [
            "Act as a professional prompt engineer. Describe this image in a very detailed English prompt for an AI image generator (like Midjourney or DALL-E). Focus on subject details, clothing, hair, lighting, and artistic style.",
            {
                "mime_type": "image/jpeg",
                "data": bytes(image_data)
            }
        ]
        
        # Panggil Gemini
        response = vision_model.generate_content(content_payload)
        
        # Kirim hasil
        await msg.edit_text(f"✅ **Hasil Prompt dari Foto:**\n\n`{response.text}`", parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Error Vision: {e}")
        await msg.edit_text(f"Waduh error Boss: {e}")

# --- FUNGSI PROMPT GENERATOR MANUAL (ALUR START) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Laki-laki", "Perempuan"]]
    await update.message.reply_text(
        "Halo Boss! Mau buat prompt?\nPilih gender di bawah atau **langsung kirim FOTO** untuk dibaca AI:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("Gaya rambut? (contoh: Undercut, Long wavy, Bald):", reply_markup=ReplyKeyboardRemove())
    return HAIR_STYLE

async def get_hair_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_style'] = update.message.text
    await update.message.reply_text("Warna rambut? (contoh: Hitam, Blonde, Silver):")
    return HAIR_COLOR

async def get_hair_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_color'] = update.message.text
    await update.message.reply_text("Pakai baju apa? (contoh: Hoodie, Batik, Jas):")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['clothes'] = update.message.text
    await update.message.reply_text("Latar belakang? (contoh: Hutan, Kota tua, Pantai):")
    return BACKGROUND

async def get_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['background'] = update.message.text
    reply_keyboard = [["1:1", "16:9", "9:16"]]
    await update.message.reply_text("Pilih Ratio Gambar:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return RATIO

async def generate_manual_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ratio = update.message.text
    u = context.user_data
    
    # Merangkai prompt manual
    final_prompt = (
        f"A high-quality photo of a {u['gender']} with {u['hair_color']} {u['hair_style']} hair, "
        f"wearing {u['clothes']}, standing in {u['background']}, "
        f"highly detailed, 8k resolution, cinematic lighting --ar {ratio}"
    )
    
    await update.message.reply_text(
        f"✅ **Prompt Manual Berhasil:**\n\n`{final_prompt}`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# 3. MAIN FUNCTION
def main():
    # Ambil Token dari Railway Variable
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Error: TELEGRAM_TOKEN tidak ditemukan!")
        return

    app = Application.builder().token(token).build()

    # Handler untuk alur manual (Start -> Tanya jawab)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
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

    # Tambahkan handler foto (Image to Prompt)
    app.add_handler(MessageHandler(filters.PHOTO, handle_image_to_prompt))
    
    # Tambahkan handler percakapan manual
    app.add_handler(conv_handler)
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
