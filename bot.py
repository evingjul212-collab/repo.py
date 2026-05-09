# -*- coding: utf-8 -*-
"""
Telegram Bot – Story Generator dengan Google Gemini (atau provider lain).

Fitur utama:
- Pilih genre (RomCom / Adventure)
- Pilih model AI via inline‑keyboard (daftar otomatis dari config)
- Simpan story, prompt terakhir, dan histori di MongoDB
- Regenerate scene dengan model lain atau revisi manual
- Replay story (tanpa menulis ke disk)
- Rate‑limit sederhana, logging, dan error handling

Author: ChatGPT – dimodifikasi oleh Anda
"""

import logging
import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------------------------
# Local modules (pastikan sudah ada)
# ----------------------------------------------------------------------
from memory import (
    init_user,
    set_genre,
    get_user,
    update_story,
    set_last_scene,
    get_last_scene,
    get_full_story,
    save_last_prompt,
    get_last_prompt,
    users,          # Mongo collection (Motor)
)
from ai_engine import generate               # async (prompt, model) -> (text, model_used)
from prompt_builder import build_prompt
from config import BOT_TOKEN, AVAILABLE_MODELS

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Rate‑limit (max 5 concurrent AI requests)
# ----------------------------------------------------------------------
SEMAPHORE = asyncio.Semaphore(5)

async def _generate_limited(prompt: str, model_name: str):
    async with SEMAPHORE:
        return await generate(prompt, model_name)

# ----------------------------------------------------------------------
# 1️⃣ /start – pilih genre
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await init_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan",   callback_data="genre_adventure")],
    ]

    await update.message.reply_text(
        "Pilih genre cerita:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# 2️⃣ Genre selection
# ----------------------------------------------------------------------
GENRE_PROMPTS = {
    "romcom": """
Romantis komedi dewasa realistis.

JANGAN:
- teleport lokasi
- ubah waktu tiba‑tiba
- karakter tahu isi pikiran lawan bicara
- karakter berbicara mustahil dari jarak jauh
- meta knowledge NPC

WAJIB:
- pertahankan lokasi
- pertahankan waktu
- transisi realistis
- dialog natural
""",
    "adventure": """
Petualangan dramatis realistis.

JANGAN:
- teleport lokasi
- lompat waktu mendadak
- meta knowledge NPC

WAJIB:
- transisi adegan jelas
- lokasi konsisten
- waktu konsisten
""",
}

async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    genre = query.data.split("_")[1]          # "romcom" atau "adventure"
    await set_genre(query.from_user.id, genre, GENRE_PROMPTS[genre])

    await query.edit_message_text(
        f"✅ Genre dipilih: *{genre}*\n\nKirim premis cerita awal.",
        parse_mode="Markdown",
    )

# ----------------------------------------------------------------------
# 3️⃣ Model menu
# ----------------------------------------------------------------------
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AVAILABLE_MODELS:
        await update.message.reply_text(
            "⚠️ Tidak ada model AI yang terdaftar di `config.AVAILABLE_MODELS`."
        )
        return

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"model_{model_name}")]
        for label, model_name in AVAILABLE_MODELS.items()
    ]
    await update.message.reply_text(
        "Pilih model AI:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# 4️⃣ Pilih model (inline callback)
# ----------------------------------------------------------------------
async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    model_name = query.data.removeprefix("model_")
    await users.update_one(
        {"_id": query.from_user.id},
        {"$set": {"selected_model": model_name}},
    )
    await query.edit_message_text(f"✅ Model aktif:\n\n`{model_name}`", parse_mode="Markdown")

# ----------------------------------------------------------------------
# 5️⃣ Chat engine – core story generation
# ----------------------------------------------------------------------
MAX_INPUT_LEN = 3500
MAX_OUTPUT_LEN = 4000

async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_msg = update.message.text.strip()

    if len(user_msg) > MAX_INPUT_LEN:
        await update.message.reply_text(
            f"⚠️ Pesan terlalu panjang ({len(user_msg)} karakter). "
            f"Gunakan ≤ {MAX_INPUT_LEN} karakter."
        )
        return

    data = await get_user(user_id)
    if not data or data.get("state") != "STORY":
        return

    story = data["story"]

    # build final prompt
    prompt = build_prompt(story, user_msg)
    await save_last_prompt(user_id, prompt)

    # typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    selected_model = data.get("selected_model", "gemini-2.5-flash")
    log.info("User %s – model %s", user_id, selected_model)

    try:
        ai_text, model_used = await _generate_limited(prompt, selected_model)
    except Exception as exc:
        log.exception("Generate failed")
        await update.message.reply_text(
            "❌ Terjadi error saat memanggil AI. Coba lagi nanti."
        )
        return

    # Fallback handling (optional)
    if model_used == "fallback":
        await update.message.reply_text(
            ai_text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔁 Retry Last Prompt", callback_data="retry_last")]]
            ),
        )
        return

    # Simpan scene ke DB
    await update_story(user_id, story, ai_text, user_msg)
    await set_last_scene(user_id, prompt, ai_text, story)

    # Inline keyboard untuk Regenerate / Replay
    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")],
        [InlineKeyboardButton("📖 Replay Story", callback_data="replay")],
    ]

    safe_text = ai_text[:MAX_OUTPUT_LEN]
    await update.message.reply_text(
        f"{safe_text}\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# 6️⃣ Regenerate flow
# ----------------------------------------------------------------------
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    last_scene = await get_last_scene(query.from_user.id)
    if not last_scene:
        await query.message.reply_text("❌ Tidak ada scene terakhir.")
        return

    # Simpan data scene di user_data untuk dipakai di langkah berikutnya
    context.user_data["regen_scene"] = last_scene

    # Tampilkan pilihan model untuk regenerate
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"regenmodel_{model_name}")]
        for label, model_name in AVAILABLE_MODELS.items()
    ]
    await query.message.reply_text(
        "Pilih model untuk regenerate:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# 7️⃣ Pilih model saat Regenerate
# ----------------------------------------------------------------------
async def select_regen_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    model_name = query.data.removeprefix("regenmodel_")
    context.user_data["regen_model"] = model_name

    await query.message.reply_text(
        "Kirim revisi / perbaikan cerita (contoh: “jangan pindah lokasi”)."
    )

# ----------------------------------------------------------------------
# 8️⃣ Rewrite (regenerate dengan revisi)
# ----------------------------------------------------------------------
async def rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "regen_scene" not in context.user_data:
        return  # bukan mode regenerate

    last = context.user_data["regen_scene"]
    model_name = context.user_data.get("regen_model", "gemini-2.5-flash")
    user_revision = update.message.text.strip()

    prompt = f"""
TUGAS:
Perbaiki scene cerita berikut.

SCENE LAMA:
{last['ai_text']}

PERBAIKAN USER:
{user_revision}

ATURAN:
- jangan ubah karakter
- jangan ubah lokasi tiba‑tiba
- jangan ubah waktu tiba‑tiba
- dialog realistis
- jangan meta‑knowledge NPC
- pertahankan inti adegan
"""

    await update.message.reply_text(f"🔄 Regenerate pakai **{model_name}**...", parse_mode="Markdown")

    try:
        ai_text, model_used = await _generate_limited(prompt, model_name)
    except Exception as exc:
        log.exception("Regenerate failed")
        await update.message.reply_text("❌ Gagal regenerate. Coba lagi.")
        return

    # bersihkan state
    context.user_data.pop("regen_scene", None)
    context.user_data.pop("regen_model", None)

    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate Lagi", callback_data="regen")]
    ]

    await update.message.reply_text(
        f"{ai_text[:MAX_OUTPUT_LEN]}\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# 9️⃣ Message router (deteksi apakah sedang dalam mode regenerate)
# ----------------------------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "regen_scene" in context.user_data:
        await rewrite(update, context)
    else:
        await chat_engine(update, context)

# ----------------------------------------------------------------------
# 🔟 Replay story (tanpa menyimpan file)
# ----------------------------------------------------------------------
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    archive = await get_full_story(query.from_user.id)
    if not archive:
        await query.message.reply_text("❌ Belum ada story.")
        return

    # Bagi teks menjadi bagian ≤ 4000 karakter
    parts = []
    buffer = ""
    for scene in archive:
        txt = (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"TURN: {scene['turn']}\n\n"
            f"USER:\n{scene['user']}\n\n"
            f"AI:\n{scene['ai']}\n\n"
        )
        if len(buffer) + len(txt) > 4000:
            parts.append(buffer)
            buffer = txt
        else:
            buffer += txt
    parts.append(buffer)

    for idx, part in enumerate(parts, start=1):
        await query.message.reply_text(
            f"📖 FULL STORY REPLAY (bagian {idx}/{len(parts)})\n\n{part}",
            disable_web_page_preview=True,
        )

# ----------------------------------------------------------------------
# 🔁 Retry last prompt
# ----------------------------------------------------------------------
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    prompt = await get_last_prompt(user_id)
    if not prompt:
        await query.message.reply_text("❌ Tidak ada prompt terakhir.")
        return

    await query.message.reply_text("🔄 Mengulang proses terakhir...")

    data = await get_user(user_id)
    selected_model = data.get("selected_model", "gemini-2.5-flash")

    try:
        ai_text, model_used = await _generate_limited(prompt, selected_model)
    except Exception as exc:
        log.exception("Retry failed")
        await query.message.reply_text("❌ Gagal mengulang prompt.")
        return

    await query.message.reply_text(f"{ai_text[:MAX_OUTPUT_LEN]}\n\n🤖 {model_used}")

# ----------------------------------------------------------------------
# ⚙️ Error handler
# ----------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Exception while handling an update:", exc_info=context.error)
    # (Opsional) beri feedback ke pengguna
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ Terjadi error internal. Silakan coba lagi nanti.")

# ----------------------------------------------------------------------
# 📋 Set Telegram command menu
# ----------------------------------------------------------------------
async def set_bot_commands(app: Application):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "🏠 Mulai / pilih genre"),
            BotCommand("model", "🤖 Pilih model AI"),
            BotCommand("replay", "📖 Replay story"),
            BotCommand("regen", "🔁 Regenerate scene"),
        ]
    )

# ----------------------------------------------------------------------
# 🚀 Main
# ----------------------------------------------------------------------
def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .post_init(set_bot_commands)      # set menu otomatis
        .build()
    )

    # COMMANDS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_menu))

    # CALLBACKS
    app.add_handler(CallbackQueryHandler(select_genre, pattern=r"^genre_"))
    app.add_handler(CallbackQueryHandler(select_model, pattern=r"^model_"))
    app.add_handler(CallbackQueryHandler(regenerate, pattern=r"^regen$"))
    app.add_handler(CallbackQueryHandler(select_regen_model, pattern=r"^regenmodel_"))
    app.add_handler(CallbackQueryHandler(replay, pattern=r"^replay$"))
    app.add_handler(CallbackQueryHandler(retry_last, pattern=r"^retry_last$"))

    # MESSAGE (text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # ERRORS
    app.add_error_handler(error_handler)

    log.info("🚀 Bot berjalan...")
    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
