import os
import logging
import httpx
import urllib.parse
import random
import asyncio
import re
from google import genai
from google.genai import types
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
)

# 1. SETUP LOGGING & AI CLIENT
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Setup Client Gemini (Pastikan API KEY di Railway sudah BENAR)
# Pakai Library google-genai terbaru (mandat Google 2026)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# INI MODEL SAKTI PUNYA BOSS, JANGAN DIGANTI! 😂
MODEL_NAME = 'gemini-2.5-flash' 

# State untuk Conversation Manual
GENDER, HAIR, COLOR, CLOTHES, BACK, RATIO = range(6)

# --- KEYBOARDS ---
def main_menu_kb():
    keyboard = [["📸 Kirim Gambar", "✍️ Buat Manual"], ["❓ Bantuan", "🔄 Reset Bot"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup([["Laki-laki", "Perempuan"]], resize_keyboard=True, one_time_keyboard=True)

def retry_vision_kb():
    # Tombol khusus kalau Vision macet/limit
    keyboard = [[InlineKeyboardButton("🔄 Coba Baca Ulang Foto", callback_data='retry_vision')]]
    return InlineKeyboardMarkup(keyboard)

# --- FUNGSI RESET & BANTUAN ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 **Panduan Nano Banana V2:**\n\n"
        "1. **📸 Kirim Gambar:** Kirim foto, AI bakal buatin prompt & lukisan baru (Anti-Cacat).\n"
        "2. **✍️ Buat Manual:** Jawab pertanyaan bot buat rakit prompt sendiri.\n"
        "3. **🔄 Reset Bot:** Pakai ini kalau bot bengong atau kuota habis.\n\n"
        "Gaskan Boss Suhu! Jangan kabur! 🚀"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🔄 Bot di-reset! Memory dibersihkan. Silakan pilih menu.", reply_markup=main_menu_kb())
    return ConversationHandler.END

# --- FUNGSI DRAW (POLLINATIONS DENGAN MANTRA ANTI-CACAT) ---
async def draw_and_send(update: Update, prompt_text: str, ratio="1:1"):
    # Gunakan pesan status yang lebih profesional ala Nano Banana
    status_msg = await update.message.reply_text("🎨 Sedang melukis... (High Quality Mode)")
    
    # Mapping ratio ke pixel agar Pollinations stabil (Flux Model)
    size_map = {"1:1": "1024x1024", "16:9": "1280x720", "9:16": "720x1280"}
    width, height = size_map.get(ratio, "1024x1024").split('x')
    
    # 1. CUCI PROMPT: Tambahkan mantra anti-cacat di belakang
    # Ambil intisari prompt dari Gemini (maks 500 karakter biar gak pusing AI-nya)
    clean_p = prompt_text.replace("\n", " ").replace("A professional photo of", "")[:500]
    
    # Mantra sakti Nano Banana buat benerin anatomi & detail
    mantra_anti_cacat = (
        ", anatomically correct, high resolution, photorealistic, 8k, "
        "highly detailed face, masterpiece, sharp focus, no distortion, "
        "no extra fingers, realistic skin texture, professional color grading"
    )
    final_p = f"{clean_p}{mantra_anti_cacat}"
    
    # Encode prompt agar aman masuk ke URL
    encoded_p = urllib.parse.quote(final_p)
    
    # Seed random biar hasilnya selalu beda tiap kali dibuat
    seed = random.randint(0, 9999999)
    
    # URL Pollinations dengan Model FLUX (Paling minim cacat saat ini) & NoLogo
    image_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={width}&height={height}&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as httpx_client:
        try:
            # Kasih waktu lebih lama (60 detik) biar server Pollinations kelar render HQ
            response = await httpx_client.get(image_url, timeout=60.0)
            
            if response.status_code == 200:
                # Kirim fotonya ke Telegram
                await update.message.reply_photo(
                    photo=image_url,
                    caption=f"✅ **Nano Banana V2 Fixed!**\nRatio: {ratio}",
                    parse_mode="Markdown",
                    reply_markup=main_menu_kb() # Tampilkan menu utama kembali
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Server lukis lagi penuh, coba sesaat lagi Boss.", reply_markup=main_menu_kb())
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Gagal kirim gambar: {e}", reply_markup=main_menu_kb())

# --- FUNGSI VISION (ANTI-BENGONG & DENGAN HANDLING LIMIT) ---
async def handle_vision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Simpan file_id foto terakhir buat jaga-jaga kalau mau retry (Anti-Macet)
    if update.message and update.message.photo:
        context.user_data['last_photo_id'] = update.message.photo[-1].file_id

    msg = await update.message.reply_text("🔍 AI sedang menganalisa gambar... (Jangan diclose)")
    
    try:
        # Ambil file foto dari user_data (lebih aman)
        file_id = context.user_data.get('last_photo_id')
        photo_file = await context.bot.get_file(file_id)
        img_bytes = await photo_file.download_as_bytearray()
        
        # Eksekusi Vision di thread terpisah agar bot gak 'bengong'
        loop = asyncio.get_event_loop()
        def call_gemini():
            # Instruksi Professional Prompt Engineer (Ala Nano Banana)
            # Dipaksa to-the-point agar Pollinations gak bingung
            instruction = (
                "Act as a professional prompt engineer for AI image generators (Midjourney/Flux). "
                "Analyze this image and create a highly detailed 1-paragraph prompt in English. "
                "Do NOT give a story, give visual descriptions. Focus on subject, fabric texture, hair style, lighting, and camera perspective."
            )
            return client.models.generate_content(
                model=MODEL_NAME, # INI GEMINI 2.5 JOS Boss Suhu!
                contents=[
                    instruction,
                    types.Part.from_bytes(data=bytes(img_bytes), mime_type='image/jpeg')
                ]
            )
        
        # Proses Panggil Gemini 2.5 (Async)
        response = await loop.run_in_executor(None, call_gemini)
        
        prompt_result = response.text
        await msg.edit_text(f"📝 **Prompt AI (Nano Banana V2):**\n\n`{prompt_result}`", parse_mode="Markdown")
        
        # Langsung gass buat gambarnya (Otomatis 1:1) dengan MANTRA ANTI-CACAT
        await draw_and_send(update, prompt_result)
        
    except Exception as e:
        err_msg = str(e)
        logging.error(f"Vision Error: {e}")
        
        # Handling Kuota Habis (Error 429) - Cooldown otomatis
        wait_time = re.search(r"retry in (\d+\.?\d*)s", err_msg)
        
        if "429" in err_msg:
            seconds = wait_time.group(1) if wait_time else "60"
            await msg.edit_text(
                f"⏳ **Kuota Habis Boss Suhu!**\nGoogle minta istirahat sebentar.\n\nSilakan klik tombol ulang dalam **{seconds} detik** lagi!",
                reply_markup=retry_vision_kb()
            )
        else:
            await msg.edit_text(
                f"❌ **Error:** {err_msg}\nMau coba ulang?",
                reply_markup=retry_vision_kb()
            )

# --- CALLBACK HANDLER UNTUK TOMBOL RETRY (ANTI-MACET) ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'retry_vision':
        # Panggil lagi fungsi handle_vision secara manual
        await handle_vision(query, context)

# --- ALUR MANUAL PROMPT GENERATOR (STATE MACHINE) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bersihkan state user data jika ada sisa
    context.user_data.clear()
    await update.message.reply_text("Siap melayani Boss Suhu! Pilih mode:", reply_markup=main_menu_kb())
    return ConversationHandler.END

async def manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bersihkan user data sebelum mulai alur baru
    context.user_data.clear()
    await update.message.reply_text("Oke, pilih Gender subyek:", reply_markup=gender_kb())
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['g'] = update.message.text
    await update.message.reply_text("Rambut (Gaya & Warna)? (contoh: Undercut Pirang, Long Wavy Hitam)", reply_markup=ReplyKeyboardRemove())
    return HAIR

async def get_hair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['h'] = update.message.text
    await update.message.reply_text("Pakaian & Aksesoris? (contoh: Kebaya Merah, Batik Modern)")
    return COLOR

async def get_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c'] = update.message.text
    await update.message.reply_text("Latar Belakang & Suasana? (contoh: Hutan Pinus, Kota Masa Depan)")
    return CLOTHES

async def get_clothes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cl'] = update.message.text
    await update.message.reply_text("Pilih Ratio:", reply_markup=ReplyKeyboardMarkup([["1:1", "16:9", "9:16"]], resize_keyboard=True))
    return RATIO

async def final_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = update.message.text
    u = context.user_data
    # Rangkai Prompt Professional ala Nano Banana
    prompt = f"Photo of {u['g']}, {u['h']} hair, wearing {u['c']},standing in {u['cl']}, highly detailed, 8k, cinematic lighting"
    
    await update.message.reply_text(f"✅ **Prompt:**\n\n`{prompt}`", parse_mode="Markdown")
    # Langsung Gambar sesuai Ratio pilihan! (MANTRA ANTI-CACAT Otomatis ditambahkan di fungsi draw)
    await draw_and_send(update, prompt, ratio=r)
    return ConversationHandler.END

# --- MAIN RUNNER (ANTI-BENGONG) ---
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Error: Variabel TELEGRAM_TOKEN tidak ditemukan!")
        return
    
    # Gunakan build() tanpa parameter khusus untuk compatibility
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
        # Reset dan Bantuan didaftarkan di fallbacks agar user bisa kabur di tengah jalan
        fallbacks=[MessageHandler(filters.Regex("^🔄 Reset Bot$"), reset_bot), MessageHandler(filters.Regex("^❓ Bantuan$"), help_command)],
    )

    # Handler Utama
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^📸 Kirim Gambar$"), lambda u,c: u.message.reply_text("Silakan kirim fotonya Boss!")))
    application.add_handler(MessageHandler(filters.Regex("^❓ Bantuan$"), help_command))
    application.add_handler(MessageHandler(filters.Regex("^🔄 Reset Bot$"), reset_bot))
    # Handler Foto (Otomatis) dengan HANDLING ANTI-MACET
    application.add_handler(MessageHandler(filters.PHOTO, handle_vision))
    # Handle tombol retry (Callback)
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(conv_handler)
    
    print("Bot Nano Banana V2 Fixed Ready Boss Suhu! 🚀")
    application.run_polling()

if __name__ == "__main__":
    main()
    
