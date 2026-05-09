# bot.py
import os, logging, asyncio
import g4f
from g4f.models import Model          # ← enum yang berisi semua model
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# -------------------------------------------------
# LOGGING
# -------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------------------------------------
# KONFIGURASI
# -------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("⚠️ Set environment variable TELEGRAM_TOKEN first.")

# -------------------------------------------------
# FUNGSI AI
# -------------------------------------------------
async def answer_ai(user_prompt: str) -> str:
    """
    Query g4f dengan model yang ada di enum `Model`.
    Jika terjadi error (mis. provider down) kita fallback ke model lain.
    """
    # Pilihan model – Anda bisa ganti ke Model.gpt_4 jika ingin performa lebih tinggi
    preferred_models = [
        Model.gpt_3_5_turbo,
        Model.gpt_4,                 # fallback kalau 3.5 lagi error
    ]

    for m in preferred_models:
        try:
            # g4f.ChatCompletion.create mengembalikan string (atau generator)
            response = g4f.ChatCompletion.create(
                model=m,
                messages=[{"role": "user", "content": user_prompt}],
                # optional: pilih provider secara spesifik
                # provider=g4f.Provider.Bing,
                # timeout=60,
            )
            return response
        except Exception as e:
            logger.warning(
                f"Model {m.name} gagal ({type(e).__name__}): {e}. Coba model berikut..."
            )
            # lanjut ke model berikutnya
            continue

    # Jika semua model gagal, beri fallback pesan manual
    return "Maaf, sepertinya layanan AI sedang bermasalah. Silakan coba lagi nanti."

# -------------------------------------------------
# HANDLER TELEGRAM
# -------------------------------------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot AI gratis (g4f). Kirim pesan apa saja, saya akan menjawab."
    )

async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text.strip()
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    answer = await answer_ai(user_msg)
    await update.message.reply_text(answer)

async def error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception while handling update", exc_info=context.error)

# -------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_error_handler(error)

    logger.info("🚀 Bot mulai polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
