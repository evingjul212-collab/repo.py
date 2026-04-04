import os, logging
import google.generativeai as genai
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters

# Setup AI - Ganti model_name sesuai yang Boss pakai (2.5)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash') # <-- Edit di sini Boss!

GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

async def handle_vision(update, context):
    msg = await update.message.reply_text("🔍 AI Vision sedang bekerja...")
    try:
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        # Prompt sesuai standar "Professional Engineer" yang Boss mau
        resp = model.generate_content([
            "Professional Prompt Engineer: Describe this image for AI Generator in 1 detailed paragraph.",
            {"mime_type": "image/jpeg", "data": bytes(img_bytes)}
        ])
        await msg.edit_text(f"✅ **AI Result:**\n\n`{resp.text}`", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"Error: {e}")

# ... (Sisa alur Manual tetap sama seperti sebelumnya) ...

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    
    # Handler Foto (Otomatis)
    app.add_handler(MessageHandler(filters.PHOTO, handle_vision))
    
    # Handler Manual (Step-by-step)
    # (Pastikan Entry Point-nya cocok dengan teks di tombol Bar Bawah Boss)
    
    app.run_polling()

if __name__ == "__main__":
    main()
