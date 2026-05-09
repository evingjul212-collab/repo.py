# -------------------------------------------------
# bot.py – contoh lengkap
# -------------------------------------------------
import os
import logging
import asyncio
from typing import List, Tuple, Optional

from telegram import Update, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import g4f
from g4f.models import Model  # enum berisi semua model yang didukung

# -------------------------------------------------
# Konfigurasi logging
# -------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# Helper – menyimpan cache model yang berhasil
# -------------------------------------------------
# *cache_mem* hanya bertahan selama proses container hidup.
# Jika Anda ingin persisten (terpakai setelah restart), simpan ke file / DB.
_successful_model: Optional[Model] = None


def set_successful_model(m: Model) -> None:
    """Simpan model yang berhasil dipakai (cache in‑memory)."""
    global _successful_model
    _successful_model = m


def get_successful_model() -> Optional[Model]:
    """Ambil model cache, atau None bila belum ada."""
    return _successful_model


# -------------------------------------------------
# AUTO‑SCAN: urutan model yang akan dicoba
# -------------------------------------------------
def list_all_models() -> List[Model]:
    """
    Mengembalikan semua nilai enum Model yang tersedia.
    Urutan default: gpt_3_5_turbo → gpt_4 → gpt_4_1106_preview → …
    Anda bebas mengubah urutan sesuai kebutuhan.
    """
    # Contoh urutan prioritas – gunakan yang paling “murah”/cepat dulu.
    priority = [
        Model.gpt_3_5_turbo,
        Model.gpt_4,
        Model.gpt_4_1106_preview,
        Model.gpt_4o,
        Model.gpt_4o_mini,
    ]

    # Pastikan semua item memang ada di enum (untuk versi g4f yang lebih lama)
    available = [m for m in priority if hasattr(Model, m.name)]
    # Jika ada model lain di enum yang tidak termasuk di atas, tambahkan di akhir.
    extra = [m for m in Model if m not in available]
    return available + extra


# -------------------------------------------------
# AI ANSWER FUNCTION
# -------------------------------------------------
async def answer_ai(user_prompt: str) -> str:
    """
    Kirim `user_prompt` ke layanan g4f dengan pencarian otomatis
    atas model yang berfungsi.
    """
    # 1️⃣ Cek cache dulu – kalau model sebelumnya berhasil, gunakan dulu.
    cached = get_successful_model()
    if cached:
        try:
            logger.info(f"🧪 Mencoba model cache: {cached.name}")
            resp = g4f.ChatCompletion.create(
                model=cached,
                messages=[{"role": "user", "content": user_prompt}],
                # provider=g4f.Provider.Bing,   # opsional
            )
            return resp
        except Exception as e:
            logger.warning(
                f"Cache model {cached.name} gagal ({type(e).__name__}): {e}. "
                "Akan scan model lain..."
            )
            # Hapus cache bila ternyata tidak lagi berfungsi
            set_successful_model(None)

    # 2️⃣ Scan semua model yang tersedia
    for model in list_all_models():
        try:
            logger.info(f"🔎 Mencoba model: {model.name}")
            resp = g4f.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": user_prompt}],
                # provider=g4f.Provider.Bing,   # opsional, bisa di‑set dinamis
                # timeout=60,
            )
            # Jika sampai sini tidak exception, berarti berhasil
            set_successful_model(model)          # simpan sebagai cache
            logger.info(f"✅ Model berhasil: {model.name}")
            return resp
        except Exception as e:
            # Tulis log singkat, terus lanjut ke model berikutnya
            logger.warning(
                f"Model {model.name} gagal ({type(e).__name__}): {e}"
            )
            continue

    # 3️⃣ Semua gagal → fallback text
    logger.error("❌ Semua model g4f gagal. Mengirim fallback.")
    return (
        "Maaf, layanan AI sedang tidak tersedia. "
        "Silakan coba lagi dalam beberapa menit."
    )


# -------------------------------------------------
# HANDLER TELEGRAM
# -------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Halo! Saya bot AI dengan auto‑scan model. "
        "Ketik apa saja dan saya akan menjawab."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Terima pesan pengguna, panggil AI, kirim balasan."""
    user_msg = update.message.text.strip()
    if not user_msg:
        return

    # Tampilkan “mengetik…” supaya pengguna tahu kita sedang bekerja
    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                      action=ChatAction.TYPING)

    try:
        answer = await answer_ai(user_msg)
        await update.message.reply_text(answer)
    except Exception as exc:  # catch‑all, supaya bot tidak crash
        logger.exception("❗️ Error saat memanggil answer_ai")
        await update.message.reply_text(
            "Maaf, terjadi kesalahan internal. "
            "Silakan coba lagi atau hubungi pembuat bot."
        )


# -------------------------------------------------
# MAIN – inisialisasi aplikasi Telegram
# -------------------------------------------------
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("🛑 Variabel lingkungan TELEGRAM_TOKEN belum di‑set!")

    app = Application.builder().token(token).build()

    # /start
    app.add_handler(CommandHandler("start", start))

    # Semua teks (kecuali perintah) masuk ke handler ini
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   handle_message))

    # Jalankan bot dengan polling (atau webhook bila Anda ubah nanti)
    logger.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
