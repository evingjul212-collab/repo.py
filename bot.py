#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Bot – Gemini / Gemma
* User memilih model lewat tombol inline (tidak perlu mengetik).
* Daftar model (Gemini + semua varian Gemma) dapat di‑update secara dinamis.
"""

import os
import asyncio
import logging
from google import genai
from typing import Dict, List, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Daftar model yang dapat dipilih (statik)
# ----------------------------------------------------------------------
# Nama‑nama **tanpa** prefix "models/".  Urutan tidak penting, hanya agar
# mudah dibaca di /models dan pada tombol.
AVAILABLE_MODELS: List[str] = [
    # ==== Gemini =======================================================
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.5-flash",
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-flash-preview-tts",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-tts-preview",
    "gemini-pro-latest",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    # ==== Gemma ========================================================
    "gemma-3-1b-it",
    "gemma-3-4b-it",
    "gemma-3-12b-it",
    "gemma-3-27b-it",
    "gemma-3n-e2b-it",
    "gemma-3n-e4b-it",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
]

# ----------------------------------------------------------------------
# In‑memory state: chat_id → model_name
# ----------------------------------------------------------------------
_CHAT_STATE: Dict[int, str] = {}

def set_model(chat_id: int, model: str) -> None:
    """Simpan pilihan model untuk satu chat."""
    _CHAT_STATE[chat_id] = model.lower()

def get_model(chat_id: int) -> str:
    """Model yang dipakai untuk chat ini. Default = gemini‑2.5‑flash."""
    return _CHAT_STATE.get(chat_id, "gemini-2.5-flash")

# ----------------------------------------------------------------------
# (Opsional) Dapatkan semua model Gemma secara dinamis dari API Gemini
# ----------------------------------------------------------------------
async def fetch_dynamic_gemma() -> List[str]:
    """
    Ambil semua model yang mengandung kata “gemma” dari layanan Google.
    Hasilnya berupa list nama (tanpa prefix “models/”).
    """
    import google.generativeai as genai
    from google.api_core import exceptions as google_exceptions

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diset")
    genai.configure(api_key=api_key)

    def _list():
        return genai.list_models()

    try:
        models = await asyncio.to_thread(_list)
    except google_exceptions.GoogleAPICallError as err:
        log.error("Gagal ambil daftar model: %s", err)
        return []

    gemma = [
        m.name.replace("models/", "")
        for m in models
        if "gemma" in m.name.lower()
    ]
    return sorted(gemma)

# ----------------------------------------------------------------------
# Fungsi untuk meng‑query Gemini / Gemma
# ----------------------------------------------------------------------
async def ask_gemini(model_name: str, prompt: str) -> str:
    """Kirim prompt ke model yang dipilih dan kembalikan teks hasilnya."""
    # import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diset")
    genai.configure(api_key=api_key)

    full_name = f"models/{model_name}"
    model = genai.GenerativeModel(full_name)

    # generate_content_async tersedia pada versi >=0.5
    response = await model.generate_content_async(prompt)

    # Beberapa model mengembalikan .text langsung, yang lain .parts
    if getattr(response, "text", None):
        return response.text.strip()
    # gabungkan semua part (biasanya .text)
    return "".join(p.text for p in response.parts).strip()

# ----------------------------------------------------------------------
# Helper – Membuat Inline Keyboard (dengan pagination)
# ----------------------------------------------------------------------
PAGE_SIZE = 8      # berapa tombol per halaman (maks 10 untuk UI yang rapi)

def _chunk(lst: List[str], size: int) -> List[List[str]]:
    """Bagi list menjadi sub‑list berukuran `size`."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]

def make_keyboard(page: int = 0) -> Tuple[InlineKeyboardMarkup, int]:
    """
    Buat `InlineKeyboardMarkup` untuk halaman `page`.
    Mengembalikan (markup, total_pages).
    """
    chunks = _chunk(sorted(AVAILABLE_MODELS), PAGE_SIZE)
    total_pages = len(chunks)

    # Pastikan page berada di rentang yang valid
    page = max(0, min(page, total_pages - 1))

    buttons = [
        [InlineKeyboardButton(txt, callback_data=f"SET#{txt}")]
        for txt in chunks[page]
    ]

    # Tambahkan navigasi bila diperlukan
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"PAGE#{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"PAGE#{page+1}"))
    if nav:
        buttons.append(nav)

    # Tombol “Batal” (opsional)
    buttons.append([InlineKeyboardButton("❌ Batal", callback_data="CANCEL")])

    return InlineKeyboardMarkup(buttons), total_pages

# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya bot Gemini/Gemma.\n\n"
        "📌 Perintah utama:\n"
        "• /models → tampilkan semua model\n"
        "• /setmodel → pilih model lewat tombol\n"
        "Model default = **gemini-2.5-flash**",
        parse_mode="Markdown",
    )

async def list_models(update: Update, _: ContextTypes.DEFAULT_TYPE):
    lines = [f"• `{m}`" for m in sorted(AVAILABLE_MODELS)]
    txt = "*Model yang dapat dipilih*:\n" + "\n".join(lines)
    await update.message.reply_text(txt, parse_mode="Markdown")

async def setmodel_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """
    Kirimkan keyboard agar user memilih model.
    Parameter tambahan tidak diperlukan; semua pilihan disajikan.
    """
    markup, _ = make_keyboard(page=0)
    await update.message.reply_text(
        "🛠️ Pilih model yang ingin Anda gunakan:",
        reply_markup=markup,
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tangani callback dari InlineKeyboard."""
    query = update.callback_query
    await query.answer()          # menghilangkan “Loading…” di UI

    data = query.data

    # ------------------- Batal -------------------
    if data == "CANCEL":
        await query.edit_message_text("❎ Pemilihan model dibatalkan.")
        return

    # ------------------- Pagination -------------------
    if data.startswith("PAGE#"):
        page = int(data.split("#")[1])
        markup, _ = make_keyboard(page)
        await query.edit_message_reply_markup(reply_markup=markup)
        return

    # ------------------- Set Model -------------------
    if data.startswith("SET#"):
        model_name = data.split("#")[1]
        chat_id = query.message.chat.id
        set_model(chat_id, model_name)

        await query.edit_message_text(
            f"✅ Model untuk chat ini **di‑set ke** `{model_name}`.",
            parse_mode="Markdown",
        )
        return

    # (fallback – tidak akan pernah tercapai)
    await query.edit_message_text("⚠️ Tindakan tidak dikenali.")

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima pesan normal, kirim ke model yang telah dipilih."""
    chat_id = update.effective_chat.id
    model = get_model(chat_id)

    # Tunjukkan “mengetik” ke user
    await context.bot.send_chat_action(
        chat_id=chat_id,
        action=constants.ChatAction.TYPING,
    )

    prompt = update.message.text or ""

    try:
        reply = await ask_gemini(model, prompt)
        await update.message.reply_text(reply)
    except Exception as exc:
        log.exception("⚡️ Gemini/Gemma error")
        await update.message.reply_text(
            f"❌ Terjadi error pada API:\n<code>{exc}</code>",
            parse_mode="HTML",
        )

# ----------------------------------------------------------------------
# Main – entry point (Railway, Heroku, dll.)
# ----------------------------------------------------------------------
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("🛑 Variable TELEGRAM_TOKEN belum diset")

    # -------------------------------------------------
    # (Opsional) Tambahkan model Gemma yang ditemukan secara dinamis
    # -------------------------------------------------
    try:
        loop = asyncio.get_event_loop()
        dyn_gemma = loop.run_until_complete(fetch_dynamic_gemma())
        for m in dyn_gemma:
            if m not in AVAILABLE_MODELS:
                AVAILABLE_MODELS.append(m)
        if dyn_gemma:
            log.info("✅ Ditambahkan %d model Gemma dinamis.", len(dyn_gemma))
    except Exception as e:
        log.warning("⚠️ Gagal memperbarui model Gemma secara dinamis: %s", e)

    # -------------------------------------------------
    # Buat aplikasi telegram
    # -------------------------------------------------
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("models", list_models))
    app.add_handler(CommandHandler("setmodel", setmodel_cmd))

    # Callback‑query (tombol)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Semua pesan teks (bukan perintah) diproses oleh `answer`
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))

    log.info("🚀 Bot mulai polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
