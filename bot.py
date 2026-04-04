import os
import logging
import httpx
import urllib.parse
import random
from google import genai
from google.genai import types
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
)

# 1. SETUP LOGGING & AI CLIENT
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Setup Client Gemini dengan Library Baru
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Ganti MODEL_NAME sesuai hasil oprek Boss (misal: 'gemini-2.5-flash')
MODEL_NAME = 'gemini-2.0-flash' 

# State untuk Conversation Manual
GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

# --- FUNGSI UTAMA DRAW (POLLINATIONS) ---
async def draw_and_send(update: Update, prompt_text: str, ratio="1:1"):
    # Mapping ratio ke pixel agar Pollinations stabil (Flux Model)
    size_map = {"1:1": "1024x1024", "16:9": "1280x720", "9:16": "720x1280"}
    width, height = size_map.get(ratio, "1024x1024").split('x')
    
    status_msg = await update.message.reply_text("🎨 Sedang melukis gambar (Model: Flux)... Tunggu bentar Boss.")
    
    # Encode prompt agar aman masuk ke URL
    # Potong jika terlalu panjang (>800 karakter) agar URL tidak error
    clean_p = prompt_text.replace("\n", " ")[:800]
    encoded_p = urllib.parse.quote(clean_p)
    
    # Seed random biar hasilnya selalu beda tiap kali dibuat
    seed = random.randint(0, 999999)
    
    # URL Pollinations dengan Model Flux (Gacor buat detail orang)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as httpx_client:
        try:
            # Kita coba ambil gambarnya dulu buat mastiin link-nya aktif
            # Timeout 50 detik karena generate gambar butuh waktu
            response = await httpx_client.get(image_url, timeout=50.0)
            
            if response.status_code == 200:
                # Kirim fotonya ke Telegram
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Ini Hasil Lukisannya Boss!**\n\nPrompt: _{clean_p[:150]}..._\nRatio: {ratio}",
                    parse_mode="Markdown",
                    reply_markup=main_menu_kb() # Tampilkan menu utama kembali
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Server lukis lagi penuh, coba sesaat lagi Boss.")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Gagal kirim gambar: {e}", reply_markup=main_menu_kb())

# --- KEYBOARDS & MENU ---
def main_menu_kb():
    # Menampilkan menu utama di toolbar bot
    keyboard = [["📸 Kirim Gambar", "✍️ Buat Manual"], ["❓ Bantuan", "🔄 Reset Bot"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def gender_kb():
    # Menampilkan pilihan gender saat manual mode
    return ReplyKeyboardMarkup([["Laki-laki", "Perempuan"]], resize_keyboard=True, one_time_keyboard=True)

# --- FUNGSI IMAGE TO PROMPT (Otomatis pakai AI Vision) ---
async def handle_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 AI sedang membaca gambar Boss...")
    try:
        # Download foto
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        
        # Instruksi Professional Prompt Engineer (Ala Nano Banana)
        instruction = (
            "Act as a professional prompt engineer for AI image generators (Midjourney/Flux). "
            "Analyze this image and create a highly detailed 1-paragraph prompt in English. "
            "Include precise details about subject, clothing fabric, hair style, lighting, and camera perspective."
        )
        
        # Panggil Gemini dengan Library Baru
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                instruction,
                types.Part.from_bytes(data=bytes(img_bytes), mime_type='image/jpeg')
            ]
        )
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **AI Prompt Dihasilkan:**\n\n`{prompt_result}`", parse_mode="Markdown")
        
        # Langsung gass buat gambarnya (Otomatis 1:1)
        await draw_and_send(update, prompt_result)
        
    except Exception as e:
        await msg.edit_text(f"Error baca gambar Boss: {e}", reply_markup=main_menu_kb())

# --- ALUR MANUAL PROMPT GENERATOR (State Machine) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bersihkan state user data jika ada sisa
    context.user_data.clear()
    await update.message.reply_text("Siap melayani Boss! Pilih mode di bawah:", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bersihkan user data sebelum mulai alur baru
    context.user_data.clear()
    await update.message.reply_text("Oke, kita mulai manual. Pilih Gender subyek:", reply_markup=gender_kb())
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['g'] = update.message.text
    await update.message.reply_text("Gaya & Warna Rambut? (Undercut Pirang, Long Black Wavy, dll)", reply_markup=ReplyKeyboardRemove())
    return HAIR

async def get_hair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['h'] = update.message.text
    await update.message.reply_text("Pakaian? (Batik Modern, Kebaya Merah, Jas Formal)")
    return COLOR

async def get_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c'] = update.message.text
    await update.message.reply_text("Latar Belakang? (Hutan Pinus, Kota Masa Depan, Kafe Estetik)")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cl'] = update.message.text
    await update.message.reply_text("Pilih Ratio:", reply_markup=ReplyKeyboardMarkup([["1:1", "16:9", "9:16"]], resize_keyboard=True))
    return RATIO

async def final_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ratio = update.message.text
    u = context.user_data
    
    # Rangkai Prompt Professional ala engineer
    final_prompt = (
        f"A photorealistic professional portrait of {u['g']}, with {u['h']} hair, "
        f"wearing {u['c']},standing in {u['cl']}, highly detailed skin texture, cinematic lighting, 8k --ar {ratio}"
    )
    
    await update.message.reply_text(f"✅ **Prompt Manual Rangkaian AI:**\n\n`{final_prompt}`", parse_mode="Markdown")
    
    # Langsung Gambar sesuai Ratio pilihan!
    await draw_and_send(update, final_prompt, ratio=ratio)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Dibatalkan.", reply_markup=main_menu_kb())
    return ConversationHandler.END

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Error: Variabel TELEGRAM_TOKEN tidak ditemukan!")
        return

    application = Application.builder().token(token).build()

    # Handler untuk alur percakapan manual
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ Buat Manual$"), manual_start)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hair)],
            COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_color)],
            CLOTHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_clothes)],
            RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, final_manual)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🔄 Reset Bot$"), start)],
    )

    # Handler Utama
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^📸 Kirim Gambar$"), lambda u,c: u.message.reply_text("Silakan kirim fotonya Boss!")))
    application.add_handler(MessageHandler(filters.PHOTO, handle_vision))
    application.add_handler(conv_handler)
    
    print("Bot Nano Banana Lokal Ready Boss! 🚀")
    application.run_polling()

if __name__ == "__main__":
    main()
