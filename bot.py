import os
import logging
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# 1. Setup Logging untuk memantau jika ada error
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# 2. Definisi tahapan percakapan (State)
GENDER, HAIR_STYLE, HAIR_COLOR, CLOTHES, BACKGROUND, RATIO = range(6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["Laki-laki", "Perempuan"]]
    await update.message.reply_text(
        "Halo Boss! Mari buat prompt gambar.\nApa gender subyeknya?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gender'] = update.message.text
    await update.message.reply_text(
        "Apa gaya rambutnya? (contoh: Undercut, Long wavy, Hijab, Bald)", 
        reply_markup=ReplyKeyboardRemove()
    )
    return HAIR_STYLE

async def get_hair_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_style'] = update.message.text
    await update.message.reply_text("Warna rambutnya apa? (contoh: Hitam, Blonde, Neon Blue)")
    return HAIR_COLOR

async def get_hair_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hair_color'] = update.message.text
    await update.message.reply_text("Pakai baju apa? (contoh: Hoodie, Jas formal, Kaos santai)")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['clothes'] = update.message.text
    await update.message.reply_text("Latar belakangnya di mana? (contoh: Di hutan pinus, Kota masa depan, Cafe estetik)")
    return BACKGROUND

async def get_background(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['background'] = update.message.text
    reply_keyboard = [["1:1", "16:9", "9:16"]]
    await update.message.reply_text(
        "Pilih ukuran gambar (Ratio):",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    return RATIO

async def generate_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ratio'] = update.message.text
    user = context.user_data
    
    # 3. Merangkai semua input menjadi satu prompt utuh
    final_prompt = (
        f"A professional photo of a {user['gender']} with {user['hair_color']} {user['hair_style']} hair, "
        f"wearing {user['clothes']}, standing in {user['background']}, "
        f"highly detailed, 8k resolution, cinematic lighting --ar {user['ratio']}"
    )
    
    await update.message.reply_text(
        f"✅ **Prompt Berhasil Dibuat:**\n\n`{final_prompt}`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pembuatan prompt dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    # 4. Mengambil Token dari Environment Variable Railway
    token = os.getenv("TELEGRAM_TOKEN")
    
    if not token:
        print("Error: Variabel TELEGRAM_TOKEN tidak ditemukan!")
        return

    application = Application.builder().token(token).build()

    # Setup alur percakapan
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HAIR_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair_style)],
            HAIR_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair_color)],
            CLOTHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_clothes)],
            BACKGROUND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_background)],
            RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_prompt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Menjalankan bot
    application.run_polling()

if __name__ == "__main__":
    main()
