# ---------------------------------------------------------
import os
import logging
import g4f
from telegram import Update               # tetap ada
from telegram.constants import ChatAction  # ← import yang benar di v20+
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
def _choose_model() -> str | g4f.Provider:
    """
    Pilih model yang tersedia secara otomatis.
    - Coba cari atribut yang memang ada di g4f.models (gpt_3_5_turbo, gpt_4, gemini, dll).
    - Jika tidak ada satupun, gunakan provider default (Bing) yang tidak perlu model khusus.
    """
    possible_names = [
        "gpt_4",
        "gpt_4_32k",
        "gpt_3_5_turbo",
        "gpt_3_5_turbo_16k",
        "gemini",
        "claude",
        "llama2_13b",
        # tambahkan nama lain yang pernah Anda lihat di dokumentasi g4f
    ]

    for name in possible_names:
        if hasattr(g4f.models, name):
            log.info("✅ Model ditemukan: %s", name)
            return getattr(g4f.models, name)

    # Jika tidak ada, fallback ke provider yang selalu ada
    log.warning("⚠️ Tidak ada model bawaan yang terdeteksi, gunakan provider BING")
    return g4f.Provider.Bing
# ---------------------------------------------------------

async def answer_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Balas pesan pengguna dengan AI (g4f)."""
    try:
        # Dapatkan model atau provider secara dinamis
        model_or_provider = _choose_model()

        # Tunjukkan “mengetik…”
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        # Perbedaan pemanggilan:
        # - Jika yang dikembalikan adalah sebuah *model* (objek) → pakai `model=`.
        # - Jika yang dikembalikan adalah sebuah *provider* → pakai `provider=`.
        if isinstance(model_or_provider, g4f.Provider):
            answer = await g4f.ChatCompletion.create_async(
                provider=model_or_provider,
                messages=[{"role": "user", "content": update.message.text}],
            )
        else:
            answer = await g4f.ChatCompletion.create_async(
                model=model_or_provider,
                messages=[{"role": "user", "content": update.message.text}],
            )

        await update.message.reply_text(answer)

    except Exception as e:   # tangkap semua error yang mungkin terjadi
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
