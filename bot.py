import os
import logging
import httpx
import urllib.parse
import random
import asyncio
from google import genai
from google.genai import types
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
)

# 1. SETUP LOGGING & AI CLIENT
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Setup Client Gemini (Pastikan API KEY di Railway sudah BENAR)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = 'gemini-2.5-flash' # Sesuai hasil oprek Boss (2.5 atau 2.0)

# State untuk Conversation Manual
GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

# --- KEYBOARDS ---
def main_menu_kb():
    keyboard = [["📸 Kirim Gambar", "✍️ Buat Manual"], ["❓ Bantuan", "🔄 Reset Bot"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup([["Laki-laki", "Perempuan"]], resize_keyboard=True, one_time_keyboard=True)

# --- FUNGSI RESET & BANTUAN ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 **Panduan Nano Banana Lokal:**\n\n"
        "1. **📸 Kirim Gambar:** Kirim foto, AI bakal buatin prompt & gambar baru.\n"
        "2. **✍️ Buat Manual:** Jawab pertanyaan bot buat rakit prompt sendiri.\n"
        "3. **🔄 Reset Bot:** Pakai ini kalau bot bengong atau mau batal.\n\n"
        "Gaskan Boss! 🚀"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 Bot di-reset! Memory dibersihkan.", reply_markup=main_menu_kb())
    return ConversationHandler.END

# --- FUNGSI DRAW (POLLINATIONS) ---
async def draw_and_send(update: Update, prompt_text: str, ratio="1:1"):
    status_msg = await update.message.reply_text("🎨 Sedang melukis... Tunggu ya Boss.")
    
    size_map = {"1:1": "1024x1024", "16:9": "1280x720", "9:16": "720x1280"}
    width, height = size_map.get(ratio, "1024x1024").split('x')
    
    clean_p = prompt_text.replace("\n", " ")[:800]
    encoded_p = urllib.parse.quote(clean_p)
    seed = random.randint(0, 999999)
    
    image_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(image_url, timeout=60.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Hasil Lukisan Boss!**\nRatio: {ratio}",
                    reply_markup=main_menu_kb()
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Server lukis lagi sibuk Boss.")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Error gambar: {e}", reply_markup=main_menu_kb())

# --- FUNGSI VISION (BIAR GAK BENGONG) ---
async def handle_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 AI sedang menganalisa gambar... (Jangan diclose)")
    try:
        # Ambil file foto
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        
        # Eksekusi Vision di thread terpisah agar gak 'bengong'
        loop = asyncio.get_event_loop()
        def call_gemini():
            return client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    "Professional Prompt Engineer: Describe this image for AI Generator in 1 detailed paragraph. English only.",
                    types.Part.from_bytes(data=bytes(img_bytes), mime_type='image/jpeg')
                ]
            )
        
        response = await loop.run_in_executor(None, call_gemini)
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **Prompt AI:**\n\n`{prompt_result}`", parse_mode="Markdown")
        await draw_and_send(update, prompt_result)
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text(f"❌ Aduh Boss, Vision error: {e}", reply_markup=main_menu_kb())

# --- ALUR MANUAL ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Siap Boss! Pilih menu:", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Oke, pilih Gender:", reply_markup=gender_kb())
    return GENDER

async def get_gender(update, context):
    context.user_data['g'] = update.message.text
    await update.message.reply_text("Rambut (Gaya & Warna)?", reply_markup=ReplyKeyboardRemove())
    return HAIR

async def get_hair(update, context):
    context.user_data['h'] = update.message.text
    await update.message.reply_text("Pakaian & Aksesoris?")
    return COLOR

async def get_color(update, context):
    context.user_data['c'] = update.message.text
    await update.message.reply_text("Latar Belakang & Suasana?")
    return CLOTHES

async def get_clothes(update, context):
    context.user_data['cl'] = update.message.text
    await update.message.reply_text("Ratio?", reply_markup=ReplyKeyboardMarkup([["1:1", "16:9", "9:16"]], resize_keyboard=True))
    return RATIO

async def final_manual(update, context):
    r = update.message.text
    u = context.user_data
    prompt = f"Professional photo of {u['g']}, {u['h']} hair, wearing {u['c']}, in {u['cl']}, highly detailed, 8k --ar {r}"
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
            COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_color)],
            CLOTHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_clothes)],
            RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, final_manual)],
        },
        fallbacks=[MessageHandler(filters.Regex("^🔄 Reset Bot$"), reset_bot)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^📸 Kirim Gambar$"), lambda u,c: u.message.reply_text("Kirim fotonya Boss!")))
    app.add_handler(MessageHandler(filters.Regex("^❓ Bantuan$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^🔄 Reset Bot$"), reset_bot))
    app.add_handler(MessageHandler(filters.PHOTO, handle_vision))
    app.add_handler(conv)
    
    print("Bot Nano Banana Gacor Running! 🚀")
    app.run_polling()

if __name__ == "__main__":
    main()
