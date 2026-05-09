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
    - Coba cari atribut yang memang ada di g4f.models (gpt_3_5_turbo#!/usr/bin/env python3
# -------------------------------------------------
# Gemini‑Only Telegram Bot with selectable model
# -------------------------------------------------
import os
import logging
import asyncio
from typing import Dict, List

from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -------------------------------------------------
# Logging
# -------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# -------------------------------------------------
# ---------- 1️⃣ Daftar Model Gemini ----------
# -------------------------------------------------
# Daftar singkat yang akan ditampilkan ke user.
# Anda dapat menambah / mengurangi sesuai kebutuhan.
AVAILABLE_MODELS: List[str] = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-flash-preview-tts",
    "gemini-pro-latest",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
    # … (tambahkan model lain bila diinginkan)
]

# -------------------------------------------------
# ---------- 2️⃣ Penyimpanan pilihan per‑chat ----------
# -------------------------------------------------
# *In‑memory* dictionary (hilang saat restart).  
# Jika ingin *persist* gunakan blok SQLite di bawah (cukup uncomment).

_CHAT_STATE: Dict[int, str] = {}       # chat_id → model_name

# ---------------------------------------------
# Opsional: SQLite persistence (aktifkan bila butuh)
# ---------------------------------------------
# import sqlite3
# _DB_PATH = "chat_state.db"
#
# def _init_db():
#     conn = sqlite3.connect(_DB_PATH)
#     cur = conn.cursor()
#     cur.execute(
#         "CREATE TABLE IF NOT EXISTS chat_state (chat_id INTEGER PRIMARY KEY, model TEXT)"
#     )
#     conn.commit()
#     conn.close()
#
# _init_db()
#
# def _set_model_db(chat_id: int, model: str):
#     conn = sqlite3.connect(_DB_PATH)
#     cur = conn.cursor()
#     cur.execute(
#         "INSERT INTO chat_state(chat_id, model) VALUES(?,?) "
#         "ON CONFLICT(chat_id) DO UPDATE SET model=excluded.model",
#         (chat_id, model),
#     )
#     conn.commit()
#     conn.close()
#
# def _get_model_db(chat_id: int) -> str:
#     conn = sqlite3.connect(_DB_PATH)
#     cur = conn.cursor()
#     cur.execute("SELECT model FROM chat_state WHERE chat_id=?", (chat_id,))
#     row = cur.fetchone()
#     conn.close()
#     return row[0] if row else "gemini-2.5-flash"
# -------------------------------------------------


def set_model(chat_id: int, model: str) -> None:
    """Simpan pilihan model untuk chat tertentu."""
    model = model.lower()
    _CHAT_STATE[chat_id] = model
    # _set_model_db(chat_id, model)   # uncomment bila menggunakan SQLite


def get_model(chat_id: int) -> str:
    """Ambil model yang dipilih – default = gemini‑2.5‑flash."""
    # return _get_model_db(chat_id)    # uncomment bila menggunakan SQLite
    return _CHAT_STATE.get(chat_id, "gemini-2.5-flash")


# -------------------------------------------------
# ---------- 3️⃣ Fungsi pemanggilan Gemini ----------
# -------------------------------------------------
async def ask_gemini(model_name: str, prompt: str) -> str:
    """
    Kirim prompt ke Google Gemini dengan model yang diberikan.
    """
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diset di environment variables")
    genai.configure(api_key=api_key)

    # Pastikan nama model lengkap: "models/<model>"
    full_name = f"models/{model_name}"
    generative_model = genai.GenerativeModel(full_name)

    # `generate_content_async` tersedia di versi 0.5.x
    response = await generative_model.generate_content_async(prompt)
    # `response.text` terkadang None jika hasil berupa block, jadi fallback ke .parts
    if response.text:
        return response.text.strip()
    # fallback untuk output yang berupa list of Part
    return "".join(part.text for part in response.parts).strip()


# -------------------------------------------------
# ---------- 4️⃣ Bot Handlers ----------
# -------------------------------------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot Gemini yang dapat dipilih modelnya.\n"
        "Gunakan perintah berikut:\n"
        "• `/models` – lihat daftar singkat model yang tersedia.\n"
        "• `/setmodel <nama>` – pilih model untuk percakapan ini.\n"
        "Contoh: `/setmodel gemini-2.5-pro`\n"
        f"Model default saat pertama kali: **gemini-2.5-flash**"
    )


async def list_models(update: Update, _: ContextTypes.DEFAULT_TYPE):
    # Tampilkan dalam format markdown supaya mudah dibaca
    lines = [f"• `{m}`" for m in sorted(AVAILABLE_MODELS)]
    txt = "*Model Gemini yang dapat dipilih*:\n" + "\n".join(lines)
    await update.message.reply_text(txt, parse_mode="Markdown")


async def setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Perintah tidak lengkap. Pakai `/setmodel <nama>`.\n"
            "Gunakan `/models` untuk melihat daftar nama yang valid."
        )
        return

    chosen = context.args[0].lower()
    if chosen not in AVAILABLE_MODELS:
        await update.message.reply_text(
            f"❌ Model `{chosen}` tidak dikenal.\n"
            "Gunakan `/models` untuk melihat pilihan yang tersedia."
        )
        return

    set_model(update.effective_chat.id, chosen)
    await update.message.reply_text(
        f"✅ Model untuk chat ini sudah di‑set ke **{chosen}**.", parse_mode="Markdown"
    )


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    model = get_model(chat_id)

    # Tampilkan indikator “mengetik…”
    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=constants.ChatAction.TYPING,
    )

    user_prompt = update.message.text

    try:
        reply = await ask_gemini(model, user_prompt)
        await update.message.reply_text(reply)
    except Exception as e:
        log.exception("⚡️ Gemini error")
        await update.message.reply_text(
            f"❌ Terjadi error pada Gemini:\n<code>{e}</code>", parse_mode="HTML"
        )


# -------------------------------------------------
# ---------- 5️⃣ Main ----------
# -------------------------------------------------
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN belum diset di environment variables")

    app = ApplicationBuilder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", list_models))
    app.add_handler(CommandHandler("setmodel", setmodel))

    # Semua pesan teks (bukan perintah) diproses oleh `answer`
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

    log.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
, gpt_4, gemini, dll).
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
