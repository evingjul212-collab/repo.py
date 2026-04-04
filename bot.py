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

# 1. SETUP LOGGING & API
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Pakai Library google-genai terbaru
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = 'gemini-2.5-flash' # Boss ganti ke 'gemini-2.5-flash' jika sudah ready di region Boss

# State untuk Conversation Manual
GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

# --- FUNGSI DRAW (POLLINATIONS) ---
async def draw_and_send(update: Update, prompt_text: str):
    status_msg = await update.message.reply_text("🎨 Sedang melukis gambar (Model: Flux)...")
    
    # Encode prompt & potong jika terlalu panjang agar URL tidak error
    clean_prompt = prompt_text.replace("\n", " ")[:800]
    encoded_p = urllib.parse.quote(clean_prompt)
    seed = random.randint(0, 999999)
    
    # URL Pollinations dengan Model Flux (Gacor buat detail orang)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as httpx_client:
        try:
            response = await httpx_client.get(image_url, timeout=50.0)
            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Hasil Lukisan Boss!**\n\nPrompt: _{clean_prompt[:150]}..._",
                    parse_mode="Markdown",
                    reply_markup=main_menu_kb()
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Server lukis lagi penuh, coba sesaat lagi Boss.")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Gagal kirim gambar: {e}", reply_markup=main_menu_kb())

# --- KEYBOARDS ---
def main_menu_kb():
    return ReplyKeyboardMarkup([["📸 Kirim Gambar", "✍️ Buat Manual"], ["🔄 Reset Bot"]], resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup([["Laki-laki", "Perempuan"]], resize_keyboard=True, one_time_keyboard=True)

# --- HANDLER IMAGE TO PROMPT (AI VISION) ---
async def handle_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 AI sedang membaca gambar...")
    try:
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        
        # Panggil Gemini dengan Library Baru
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                "Act as a professional prompt engineer. Describe this image for an AI Generator in 1 detailed paragraph. English only.",
                types.Part.from_bytes(data=bytes(img_bytes), mime_type='image/jpeg')
            ]
        )
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **AI Prompt:**\n\n`{prompt_result}`", parse_mode="Markdown")
        
        # Langsung Gambar!
        await draw_and_send(update, prompt_result)
        
    except Exception as e:
        logging.error(f"Vision Error: {e}")
        await msg.edit_text(f"Gagal baca gambar Boss. Cek API Key atau Model Name.", reply_markup=main_menu_kb())

# --- ALUR MANUAL (STATE MACHINE) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Siap melayani Boss! Pilih menu:", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Oke Manual. Pilih Gender subyek:", reply_markup=gender_kb())
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['g'] = update.message.text
    await update.message.reply_text("Gaya rambut? (Undercut, Hijab, Long wavy)", reply_markup=ReplyKeyboardRemove())
    return HAIR

async def get_hair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['h'] = update.message.text
    await update.message.reply_text("Warna rambut? (Hitam, Pirang, Neon)")
    return COLOR

async def get_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c'] = update.message.text
    await update.message.reply_text("Pakaian? (Batik, Kebaya, Hoodie)")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cl'] = update.message.text
    await update.message.reply_text("Latar belakang? (Hutan, Kota, Kafe)")
    return BACK

async def get_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['b'] = update.message.text
    await update.message.reply_text("Pilih Ratio:", reply_markup=ReplyKeyboardMarkup([["1:1", "16:9", "9:16"]], resize_keyboard=True))
    return RATIO

async def final_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.message.text
    u = context.user_data
    # Rangkai Prompt Professional
    prompt = f"Professional photo of {u['g']}, {u['c']} {u['h']} hair, wearing {u['cl']}, in {u['b']}, highly detailed, 8k, cinematic --ar {r}"
    
    await update.message.reply_text(f"✅ **Prompt Manual:**\n\n`{prompt}`", parse_mode="Markdown")
    # Langsung Gambar!
    await draw_and_send(update, prompt)
    return ConversationHandler.END

# --- MAIN RUNNER ---
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
