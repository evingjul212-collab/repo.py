# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
Telegram bot yang hanya memakai Google Gemini API‑Key
dengan kemampuan memilih model (mis: gemini-2.5-flash, gemini-3.1-flash-lite-preview, dll.).
"""

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
    # Tambahkan model lain bila diperlukan
]

# -------------------------------------------------
# ---------- 2️⃣ Penyimpanan pilihan per‑chat ----------
# -------------------------------------------------
# In‑memory dictionary (hilang saat restart).
# Jika ingin persist gunakan SQLite (lihat komentar di bawah).

_CHAT_STATE: Dict[int, str] = {}       # chat_id -> model_name

# -------------------------------------------------
# Opsional: SQLite persistence (aktifkan bila butuh)
# -------------------------------------------------
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
#     return row[0] if row else "gemma-4-26b-a4b-it"

# -------------------------------------------------
def set_model(chat_id: int, model: str) -> None:
    """Simpan pilihan model untuk chat tertentu."""
    model = model.lower()
    _CHAT_STATE[chat_id] = model
    # _set_model_db(chat_id, model)   # uncomment bila menggunakan SQLite


def get_model(chat_id: int) -> str:
    """Ambil model yang dipilih - default = gemini-2.5-flash."""
    # return _get_model_db(chat_id)    # uncomment bila menggunakan SQLite
    return _CHAT_STATE.get(chat_id, "gemma-4-26b-a4b-it")

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

    # generate_content_async tersedia di versi 0.5.x
    response = await generative_model.generate_content_async(prompt)

    # response.text bisa None kalau output berupa Part list
    if response.text:
        return response.text.strip()
    return "".join(part.text for part in response.parts).strip()

# -------------------------------------------------
# ---------- 4️⃣ Bot Handlers ----------
# -------------------------------------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot Gemini yang dapat dipilih modelnya.\n"
        "Gunakan perintah berikut:\n"
        "• /models - lihat daftar singkat model yang tersedia.\n"
        "• /setmodel <nama> - pilih model untuk percakapan ini.\n"
        "Contoh: /setmodel gemini-2.5-pro\n"
        "Model default saat pertama kali: **gemma-4-26b-a4b-it**"
    )


async def list_models(update: Update, _: ContextTypes.DEFAULT_TYPE):
    # Tampilkan dalam format markdown supaya mudah dibaca
    lines = [f"• `{m}`" for m in sorted(AVAILABLE_MODELS)]
    txt = "*Model Gemini yang dapat dipilih*:\n" + "\n".join(lines)
    await update.message.reply_text(txt, parse_mode="Markdown")


async def setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Perintah tidak lengkap. Pakai /setmodel <nama>.\n"
            "Gunakan /models untuk melihat daftar nama yang valid."
        )
        return

    chosen = context.args[0].lower()
    if chosen not in AVAILABLE_MODELS:
        await update.message.reply_text(
            f"❌ Model `{chosen}` tidak dikenal.\n"
            "Gunakan /models untuk melihat pilihan yang tersedia."
        )
        return

    set_model(update.effective_chat.id, chosen)
    await update.message.reply_text(
        f"✅ Model untuk chat ini sudah di-set ke **{chosen}**.", parse_mode="Markdown"
    )


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    model = get_model(chat_id)

    # Tampilkan indikator "mengetik..."
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

    # Semua pesan teks (bukan command) diproses oleh answer
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

    log.info("🚀 Bot mulai polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
