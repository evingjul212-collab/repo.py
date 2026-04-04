import os
import logging
import httpx
import urllib.parse
import random
from google import genai
from google.genai import types
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
)

# 1. SETUP
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = 'gemini-2.0-flash' # Boss bisa ganti ke 2.5 sesuai pengalaman Boss

GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

# --- FUNGSI KIRIM GAMBAR (POLLINATIONS) ---
async def draw_and_send(update: Update, prompt_text: str, ratio="1:1"):
    # Mapping ratio ke pixel (Pollinations lebih stabil pakai angka pixel)
    size_map = {"1:1": "1024x1024", "16:9": "1280x720", "9:16": "720x1280"}
    width, height = size_map.get(ratio, "1024x1024").split('x')
    
    status_msg = await update.message.reply_text("🎨 Sedang melukis... (Model: Flux)")
    
    clean_p = prompt_text.replace("\n", " ")[:800]
    encoded_p = urllib.parse.quote(clean_p)
    seed = random.randint(0, 99999)
    
    image_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(image_url, timeout=60.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Hasil Lukisan!**\nRatio: {ratio}",
                    reply_markup=main_menu_kb()
                )
                await status_msg.delete()
            else:
                raise Exception("Server Busy")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Gagal Gambar: {e}\nCoba klik tombol menu lagi Boss.", reply_markup=main_menu_kb())

# --- KEYBOARDS ---
def main_menu_kb():
    return ReplyKeyboardMarkup([["📸 Kirim Gambar", "✍️ Buat Manual"], ["🔄 Reset Bot"]], resize_keyboard=True)

def retry_vision_kb():
    # Tombol khusus kalau Vision macet
    keyboard = [[InlineKeyboardButton("🔄 Coba Baca Ulang Foto", callback_data='retry_vision')]]
    return InlineKeyboardMarkup(keyboard)

# --- HANDLER IMAGE TO PROMPT (DENGAN RETRY LOGIC) ---
async def handle_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Simpan file_id foto terakhir buat jaga-jaga kalau mau retry
    if update.message.photo:
        context.user_data['last_photo_id'] = update.message.photo[-1].file_id

    msg = await update.message.reply_text("🔍 AI sedang membaca gambar...")
    
    try:
        file_id = context.user_data.get('last_photo_id')
        photo_file = await context.bot.get_file(file_id)
        img_bytes = await photo_file.download_as_bytearray()
        
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                "Act as a professional prompt engineer. Describe this image for AI Generator in 1 detailed paragraph. English only.",
                types.Part.from_bytes(data=bytes(img_bytes), mime_type='image/jpeg')
            ]
        )
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **AI Prompt:**\n\n`{prompt_result}`", parse_mode="Markdown")
        await draw_and_send(update, prompt_result) # Otomatis gambar 1:1
        
    except Exception as e:
        logging.error(f"Vision Error: {e}")
        await msg.edit_text(
            f"❌ **Macet Boss!**\nError: {e}\n\nMungkin koneksi API lagi drop. Mau coba lagi?",
            reply_markup=retry_vision_kb()
        )

# --- CALLBACK UNTUK TOMBOL RETRY ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'retry_vision':
        # Panggil lagi fungsi handle_vision secara manual
        await handle_vision(query, context)

# --- ALUR MANUAL ---
async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pilih Gender:", reply_markup=ReplyKeyboardMarkup([["Laki-laki", "Perempuan"]], resize_keyboard=True))
    return GENDER

async def get_gender(update, context):
    context.user_data['g'] = update.message.text
    await update.message.reply_text("Gaya & Warna Rambut?", reply_markup=ReplyKeyboardRemove())
    return HAIR

async def get_hair(update, context):
    context.user_data['h'] = update.message.text
    await update.message.reply_text("Pakaian & Latar Belakang?")
    return CLOTHES

async def get_clothes(update, context):
    context.user_data['c'] = update.message.text
    await update.message.reply_text("Pilih Ratio:", reply_markup=ReplyKeyboardMarkup([["1:1", "16:9", "9:16"]], resize_keyboard=True))
    return RATIO

async def final_manual(update, context):
    r = update.message.text
    u = context.user_data
    prompt = f"Photo of {u['g']}, {u['h']} hair, {u['c']}, highly detailed, 8k --ar {r}"
    await update.message.reply_text(f"✅ **Prompt:**\n`{prompt}`")
    await draw_and_send(update, prompt, ratio=r)
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Buat Manual$"), manual_start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair)],
            CLOTHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_clothes)],
            RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, final_manual)],
        },
        fallbacks=[CommandHandler("start", lambda u,c: u.message.reply_text("Reset", reply_markup=main_menu_kb()))]
    )

    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text("Siap Boss!", reply_markup=main_menu_kb())))
    app.add_handler(MessageHandler(filters.PHOTO, handle_vision))
    app.add_handler(CallbackQueryHandler(button_callback)) # Handle tombol retry
    app.add_handler(conv)
    
    print("Bot Anti-Macet Running! 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
