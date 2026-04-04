import os
import logging
import httpx
import google.generativeai as genai
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
)

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Config AI
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
vision_model = genai.GenerativeModel('gemini-1.5-flash')

GENDER, HAIR_STYLE, HAIR_COLOR, CLOTHES, BACKGROUND, RATIO = range(6)

# --- MENU UTAMA (REUSABLE) ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📸 Kirim Gambar (AI)", callback_data='mode_vision')],
        [InlineKeyboardButton("✍️ Buat Manual (Step-by-step)", callback_data='mode_manual')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo Boss! Mau buat apa hari ini?",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# --- IMAGE GENERATOR (POLLINATIONS WITH RETRY) ---
async def generate_image_action(update: Update, prompt: str):
    # Bersihkan prompt dari karakter aneh buat URL
    clean_prompt = prompt.replace(" ", "%20").replace("\n", "%20")[:500] 
    image_url = f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1024&height=1024&nologo=true&seed=42"
    
    msg = await update.message.reply_text("🎨 Sedang melukis gambar... Tunggu bentar Boss.")
    
    async with httpx.AsyncClient() as client:
        try:
            # Kita coba ambil gambarnya dulu buat mastiin link-nya aktif
            response = await client.get(image_url, timeout=30.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Hasil Lukisan:**\n\n`{prompt[:200]}...`",
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard()
                )
                await msg.delete()
            else:
                raise Exception("Server Pollinations lagi sibuk.")
        except Exception as e:
            keyboard = [[InlineKeyboardButton("🔄 Coba Lagi", callback_data='retry_last')]]
            context.user_data['last_prompt'] = prompt # Simpan buat retry
            await msg.edit_text(
                f"❌ Gagal melukis Boss: {e}\n\nMungkin server lagi penuh. Mau coba lagi?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

# --- HANDLING IMAGE TO PROMPT ---
async def handle_image_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Membaca foto dengan Gemini AI...")
    try:
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        
        # Gunakan instruksi professional seperti yang Boss mau
        instruction = "Act as a professional prompt engineer. Analyze this image and create a detailed 1-paragraph Midjourney prompt in English."
        
        response = vision_model.generate_content([
            instruction, {"mime_type": "image/jpeg", "data": bytes(img_bytes)}
        ])
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **Prompt Dihasilkan:**\n\n`{prompt_result}`", parse_mode="Markdown")
        
        # Langsung gass buat gambarnya!
        await generate_image_action(update, prompt_result)
        
    except Exception as e:
        await msg.edit_text(f"Error: {e}", reply_markup=main_menu_keyboard())

# --- CALLBACK HANDLER (BUAT TOMBOL) ---
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'mode_manual':
        await query.message.reply_text("Oke, kita mulai manual. Apa Gender subyeknya? (L/P)")
        # Di sini Boss bisa sambungin ke ConversationHandler manual lagi
    elif query.data == 'mode_vision':
        await query.message.reply_text("Silakan kirim FOTO yang mau dijadiin prompt, Boss!")
    elif query.data == 'retry_last':
        last_p = context.user_data.get('last_prompt')
        if last_p:
            await generate_image_action(query.message, last_p)

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image_vision))
    
    print("Bot is running Boss! 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
