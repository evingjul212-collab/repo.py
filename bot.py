# bot.py
import os
import logging
import asyncio

import g4f
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Bot Token ----------
# Railway (atau Heroku, Render, dll) menyimpan token sebagai environment variable.
# Pastikan variabelnya bernama TELEGRAM_TOKEN.
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    logger.error("❌  Environment variable TELEGRAM_TOKEN tidak ditemukan!")
    raise SystemExit("Set environment variable TELEGRAM_TOKEN first.")

# ---------- Helper ----------
async def answer_ai(user_text: str) -> str:
    """
    Memanggil g4f untuk mendapatkan respons AI.
    Jika provider tertentu gagal, akan coba provider lain secara otomatis.
    """
    try:
        # Pilihan model: gpt_3_5_turbo (lebih stabil) atau gpt_4 (lebih kuat)
        # Kamu bisa mengganti sesuai kebutuhan:
        # model = g4f.models.gpt_4
        model = g4f.models.gpt_3_5_turbo

        # `g4f.ChatCompletion.create` mengembalikan string langsung
        response = g4f.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": user_text}],
        )
        return response
    except Exception as e:
        logger.exception("⚡️ g4f error")
        return f"Maaf, ada masalah dengan AI: {e}"


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot AI gratis (g4f). Ketik apa saja, saya akan menjawab."
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    # Kirim 'typing...' supaya user tahu bot sedang berpikir
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    answer = await answer_ai(user_msg)
    await update.message.reply_text(answer)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log semua error."""
    logger.exception(msg="Exception while handling an update:", exc_info=context.error)


# ---------- Main ----------
def main() -> None:
    # Buat aplikasi Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Daftarkan handler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_error_handler(error_handler)

    # Jalankan bot (polling)
    logger.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    # Untuk Railway ini tidak diperlukan `asyncio.run(main())` karena `run_polling`
    # sudah men‑handle event‑loop secara internal.
    main()
