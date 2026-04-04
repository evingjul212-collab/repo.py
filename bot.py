async def handle_image_to_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Sedang menganalisa gambar... Tunggu bentar Boss.")
    
    try:
        # 1. Download foto dari Telegram ke memory
        photo_file = await update.message.photo[-1].get_file()
        image_data = await photo_file.download_as_bytearray()
        
        # 2. Format yang benar untuk Gemini (menggunakan dictionary 'parts')
        # Kita bungkus data bytes-nya ke dalam format yang diminta library terbaru
        content_parts = [
            "Describe this image in detail for an AI image generator prompt. Focus on subject, clothing, hair, lighting, and style in English.",
            {
                "mime_type": "image/jpeg",
                "data": bytes(image_data)
            }
        ]
        
        # 3. Panggil AI dengan format yang sudah diperbaiki
        response = vision_model.generate_content(content_parts)
        
        await msg.edit_text(f"✅ **Hasil Prompt dari Foto:**\n\n`{response.text}`", parse_mode="Markdown")
        
    except Exception as e:
        # Jika masih error, kita cetak di log biar gampang debug
        logging.error(f"Error detail: {e}")
        await msg.edit_text(f"Waduh error lagi Boss. Cek log Railway atau coba lagi.")
