import httpx
import urllib.parse

async def draw_and_send(update, prompt_text):
    # 1. Kasih tau user kalau lagi proses gambar
    status_msg = await update.message.reply_text("🎨 Sedang melukis gambar... Tunggu bentar Boss.")
    
    # 2. Encode prompt agar aman masuk ke URL (spasi jadi %20, dll)
    encoded_prompt = urllib.parse.quote(prompt_text)
    
    # Boss bisa atur model (flux, turbo, dll) & ukuran di sini
    # Seed=random biar hasilnya selalu beda tiap kali dibuat
    import random
    seed = random.randint(0, 99999)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&model=flux&nologo=true"

    async with httpx.AsyncClient() as client:
        try:
            # Cek dulu apakah link-nya valid (timeout 40 detik karena generate gambar butuh waktu)
            response = await client.get(image_url, timeout=40.0)
            
            if response.status_code == 200:
                # Kirim fotonya ke Telegram
                await update.message.reply_photo(
                    photo=image_url,
                    caption="✅ **Ini Hasil Lukisannya Boss!**",
                    parse_mode="Markdown"
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text("❌ Gagal melukis, server Pollinations lagi penuh Boss.")
        except Exception as e:
            await status_msg.edit_text(f"⚠️ Error pas nggambar: {e}")

# CARA PAKAI:
# Di dalam fungsi handle_vision atau generate_manual_prompt, 
# tinggal panggil: await draw_and_send(update, prompt_result)
