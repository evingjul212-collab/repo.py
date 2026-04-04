import google.generativeai as genai

# Setup Gemini (Taruh di bawah logging)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model_vision = genai.GenerativeModel('gemini-1.5-flash')

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Kasih tau user kalau bot lagi "mikir"
    message = await update.message.reply_text("Sedang membaca gambar... Tunggu bentar Boss 🔍")
    
    # 2. Ambil file foto dari Telegram
    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()
    
    # 3. Minta Gemini buat deskripsiin jadi prompt
    prompt_instruksi = "Describe this image in detail for an AI image generator prompt. Use English, focus on subject, lighting, and style."
    
    try:
        # Kirim ke AI
        response = model_vision.generate_content([
            prompt_instruksi,
            {'mime_type': 'image/jpeg', 'data': bytes(image_bytes)}
        ])
        
        await message.edit_text(f"✅ **Hasil Prompt dari Foto:**\n\n`{response.text}`", parse_mode="Markdown")
    except Exception as e:
        await message.edit_text(f"Waduh error Boss: {e}")

# Di bagian main(), tambahkan handler ini:
# application.add_handler(MessageHandler(filters.PHOTO, handle_image))
