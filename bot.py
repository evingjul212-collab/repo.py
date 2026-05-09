# ---------------------------------------------------------
import os
import logging
import g4f
from telegram import Update               # tetap
from telegram.constants import ChatAction  # ← perbaikan import
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------
async def answer_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Balas pesan pengguna dengan AI (g4f)."""
    try:
        # Pilih model secara dinamis; fallback ke manual Model() jika attribute missing
        model = getattr(g4f.models, "gpt_3_5_turbo",
                        g4f.models.Model("gpt-3.5-turbo"))  # tipe fallback
        log.info("🔧 Menggunakan model %s", model)

        # Tunjukkan bahwa bot “mengetik”
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        # Panggilan async ke g4f
        answer = await g4f.ChatCompletion.create_async(
            model=model,
            messages=[{"role": "user", "content": update.message.text}],
        )
        await update.message.reply_text(answer)

    except Exception as e:  # tangkap semua error dari g4f
        log.exception("⚡️ g4f error")
        await update.message.reply_text(
            f"❌ Terjadi error pada AI:\n<code>{e}</code>",
            parse_mode="HTML",
        )

# ---------------------------------------------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Kirimkan pesan apa saja, saya akan menjawab dengan GPT."
    )

# ---------------------------------------------------------
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("⚠️ Variable TELEGRAM_TOKEN belum diset!")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer_ai)
    )

    log.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
# ---------------------------------------------------------
