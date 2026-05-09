# -------------------------------------------------
# bot.py – Bot Telegram dengan auto‑scan model g4f
# -------------------------------------------------
import os
import logging
from typing import List, Optional

from telegram import Update, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import g4f
from g4f.models import Model   # enum yang berisi semua model yang tersedia

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# -------------------------------------------------
# Cache (in‑memory) untuk model yang sudah terbukti berhasil
# -------------------------------------------------
_successful_model: Optional[Model] = None


def set_successful_model(m: Model) -> None:
    global _successful_model
    _successful_model = m


def get_successful_model() -> Optional[Model]:
    return _successful_model


# -------------------------------------------------
# Daftar prioritas model (urutkan sesuai biaya/kecepatan)
# -------------------------------------------------
def list_all_models() -> List[Model]:
    # Urutan yang biasanya paling murah/tercepat
    priority = [
        Model.gpt_3_5_turbo,
        Model.gpt_4,
        Model.gpt_4_1106_preview,
        Model.gpt_4o,
        Model.gpt_4o_mini,
    ]

    # Pastikan semua ada di enum (untuk versi g4f yang lebih lama)
    available = [m for m in priority if hasattr(Model, m.name)]

    # Tambahkan sisa model yang tidak ada di `priority` di akhir list
    extra = [m for m in Model if m not in available]
    return available + extra


# -------------------------------------------------
# Fungsi utama: kirim prompt ke AI dengan auto‑scan model
# -------------------------------------------------
async def answer_ai(user_prompt: str) -> str:
    """
    Coba model yang sudah di‑cache dulu, bila gagal scan semua yang ada.
    Return string balasan atau fallback jika semua gagal.
    """
    # 1️⃣ Coba model cache (jika ada)
    cached = get_successful_model()
    if cached:
        try:
            log.info(f"🔎 Mencoba model cache: {cached.name}")
            resp = g4f.ChatCompletion.create(
                model=cached,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return resp
        except Exception as e:
            log.warning(f"Cache {cached.name} gagal ({type(e).__name__}): {e}")
            set_successful_model(None)          # reset cache

    # 2️⃣ Scan semua model yang tersedia
    for model in list_all_models():
        try:
            log.info(f"🔎 Mencoba model: {model.name}")
            resp = g4f.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # Jika sampai sini tidak exception, berarti berhasil
            set_successful_model(model)
            log.info(f"✅ Model berhasil: {model.name}")
            return resp
        except Exception as e:
            log.warning(f"Model {model.name} gagal ({type(e).__name__}): {e}")
            continue

    # 3️⃣ Semua gagal → fallback
    log.error("❌ Semua model g4f gagal. Mengirim fallback.")
    return (
        "Maaf, layanan AI sedang tidak tersedia. "
        "Silakan coba lagi dalam beberapa menit."
    )


# -------------------------------------------------
# Handlers Telegram
# -------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Halo! Saya bot AI dengan auto‑scan model. "
        "Ketik apa saja, saya akan menjawab."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_msg = update.message.text.strip()
    if not user_msg:
        return

    # Tunjukkan “mengetik…”
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        answer = await answer_ai(user_msg)
        await update.message.reply_text(answer)
    except Exception as exc:
        log.exception("⚡️ g4f error")
        await update.message.reply_text(
            "Terjadi kesalahan internal. Silakan coba lagi."
        )


# -------------------------------------------------
# Main – inisialisasi bot
# -------------------------------------------------
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("🛑 Env var TELEGRAM_TOKEN belum di‑set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    log.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
