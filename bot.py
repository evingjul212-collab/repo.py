import os
import logging
import httpx
import google.generativeai as genai
from telegram import ReplyKeyboardMarkup, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
)

# 1. Setup Logging & AI
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision_model = genai.GenerativeModel('gemini-2.5-flash')

# State untuk percakapan manual
GENDER, HAIR, CLOTHES, BG, RATIO = range(5)

# --- FUNGSI MENU BAR (TOMBOL DI BAWAH) ---
def main_menu_bar():
    # Ini yang bikin tombol nempel di toolbar chat
    keyboard = [
        ['📸 Kirim Gambar', '✍️ Buat Manual'],
        ['❓ Bantuan', '🔄 Reset Bot']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Siap melayani Boss! Silakan pilih menu di bawah ini:",
        reply_markup=main_menu_bar()
    )
    return ConversationHandler.END

# --- FUNGSI GENERATE GAMBAR (POLLINATIONS) ---
async def draw_image(update: Update, prompt: str):
    msg = await update.message.reply_text("🎨 Sedang melukis... Sabar ya Boss.")
    # Encoding prompt agar aman di URL
    clean_prompt = prompt.replace(" ", "%20").replace("\n", "%20")[:500]
    img_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true"
    
    try:
        # Kirim gambarnya
        await update.message.reply_photo(
            photo=img_url,
            caption=f"✅ **Hasil Gambar:**\n\n`{prompt[:200]}...`",
            parse_mode="Markdown",
            reply_markup=main_menu_bar() # Munculin menu lagi
        )
        await msg.delete()
    except Exception:
        # Opsi Ulang jika Error
        kb = [[InlineKeyboardButton("🔄 Coba Lagi", callback_data='retry')]]
        context.user_data['last_p'] = prompt
        await msg.edit_text("❌ Gagal nih Boss, server Pollinations lagi penuh. Mau coba lagi?", 
                            reply_markup=InlineKeyboardMarkup(kb))

# --- LOGIKA TOMBOL BAR ---
async def handle_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == '📸 Kirim Gambar':
        await update.message.reply_text("Silakan kirim FOTO subyeknya, nanti AI yang buatin prompt-nya!")
    elif text == '✍️ Buat Manual':
        await update.message.reply_text("Oke, kita mulai manual. Apa Gender subyeknya? (Laki-laki/Perempuan)")
        return GENDER # Ini masuk ke flow manual (kalau pakai ConvHandler)
    elif text == '🔄 Reset Bot':
        await update.message.reply_text("Bot di-reset! Silakan pilih lagi.", reply_markup=main_menu_bar())
    else:
        await update.message.reply_text("Pilih menu yang ada di bar bawah ya Boss!", reply_markup=main_menu_bar())

# --- IMAGE TO PROMPT (VISION) ---
async def vision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Gemini lagi ngintip fotonya...")
    try:
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        
        res = vision_model.generate_content([
            "Create a high-quality Midjourney prompt based on this image. 1 paragraph only.",
            {"mime_type": "image/jpeg", "data": bytes(img_bytes)}
        ])
        
        await msg.edit_text(f"📝 **Prompt Dihasilkan:**\n\n`{res.text}`", parse_mode="Markdown")
        await draw_image(update, res.text)
    except Exception as e:
        await msg.edit_text(f"Error Vision: {e}")

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    app = Application.builder().token(token).build()

    # Handler Menu Bar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, vision_handler))
    
    # Deteksi klik di Menu Bar
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_click))

    print("Bot Menu Bar Aktif, Boss! 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
