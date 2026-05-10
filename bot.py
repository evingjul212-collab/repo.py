# --------------------------------------------------------------
# bot.py
# --------------------------------------------------------------
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, AVAILABLE_MODELS
from memory import (
    init_user,
    set_genre,
    get_full_state,
    update_story,
    save_last_prompt,
    get_last_prompt,
    get_last_scene,
    set_last_scene,
    get_full_story,
)
from prompt_builder import build_prompt
from ai_engine import generate

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# /start – pilih genre
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await init_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan",   callback_data="genre_adventure")],
    ]
    await update.message.reply_text(
        "🧭 Pilih genre cerita:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ------------------------------------------------------------------
# Pilih genre (memanggil set_genre)
# ------------------------------------------------------------------
async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    genre_key = query.data.split("_")[1]   # "romcom" / "adventure"

    system_prompts = {
        "romcom": """Romantis komedi dewasa realistis.

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
        "adventure": """Petualangan dramatis realistis.

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

    await set_genre(
        query.from_user.id,
        genre_key,
        system_prompts[genre_key],
    )
    await query.edit_message_text(
        f"✅ Genre dipilih: *{genre_key}*\n\nKirim premis cerita awal.",
        parse_mode="Markdown",
    )

# ------------------------------------------------------------------
# /model – menu pilih model AI
# ------------------------------------------------------------------
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for label, name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"model_{name}")]
        )
    await update.message.reply_text(
        "🤖 Pilih model AI:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ------------------------------------------------------------------
# Pilih model (simpan di users)
# ------------------------------------------------------------------
async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    model_name = query.data.replace("model_", "")

    await context.application.bot_data.setdefault("selected_models", {})
    await context.application.bot_data["selected_models"].update(
        {query.from_user.id: model_name}
    )
    # Simpan juga ke DB (agar tetap setelah restart)
    from memory import users
    await users.update_one(
        {"_id": query.from_user.id},
        {"$set": {"selected_model": model_name}},
        upsert=True,
    )
    await query.edit_message_text(f"✅ Model aktif: `{model_name}`", parse_mode="Markdown")

# ------------------------------------------------------------------
# Chat engine – inti percakapan
# ------------------------------------------------------------------
async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_msg = update.message.text

    # Ambil metadata + story
    state = await get_full_state(user_id)
    metadata = state["metadata"]
    story = state["story"]

    # Pastikan genre sudah dipilih
    if not metadata.get("genre"):
        await update.message.reply_text(
            "⚠️ Pilih dulu genre dengan /start."
        )
        return

    # Build prompt
    prompt = build_prompt(metadata, story, user_msg)
    await save_last_prompt(user_id, prompt)

    # Pilih model (fallback ke default)
    selected_model = metadata.get("selected_model", "gemini-2.5-flash")
    log.info(f"🔎 Menggunakan model: {selected_model}")

    try:
        ai_text, model_used = await generate(prompt, selected_model)

        # Simpan scene baru
        story = await update_story(user_id, story, ai_text, user_msg)

        # Keyboard di akhir setiap jawaban
        keyboard = [
            [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")],
            [InlineKeyboardButton("📖 Replay Story", callback_data="replay")],
        ]

        safe = ai_text[:3500]   # Telegram max 4096 karakter
        await update.message.reply_text(
            safe + f"\n\n🤖 {model_used}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as exc:
        log.exception("Generate error")
        await update.message.reply_text(
            "❌ Gagal memanggil AI. Coba lagi atau pilih model lain dengan /model."
        )

# ------------------------------------------------------------------
# /regen – pilih model untuk regenerasi scene terakhir
# ------------------------------------------------------------------
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    last_scene = await get_last_scene(query.from_user.id)
    if not last_scene:
        await query.message.reply_text("⚠️ Tidak ada scene terakhir.")
        return

    # Simpan data regen ke context.user_data
    context.user_data["regen_scene"] = last_scene

    # Tampilkan pilihan model untuk regen
    keyboard = []
    for label, name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"regenmodel_{name}")]
        )
    await query.message.reply_text(
        "🔄 Pilih model untuk regenerate:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ------------------------------------------------------------------
# Pilih model untuk regen
# ------------------------------------------------------------------
async def select_regen_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    model_name = query.data.replace("regenmodel_", "")
    context.user_data["regen_model"] = model_name
    await query.message.reply_text(
        f"✅ Model regen dipilih: `{model_name}`\n\nKirim revisi / perbaikan cerita.",
        parse_mode="Markdown",
    )

# ------------------------------------------------------------------
# Rewrite (setelah user mengirim revisi)
# ------------------------------------------------------------------
async def rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "regen_scene" not in context.user_data:
        return

    last = context.user_data["regen_scene"]
    model_name = context.user_data.get("regen_model", "gemini-2.5-flash")
    user_revision = update.message.text

    prompt = f"""
TUGAS:
Perbaiki scene cerita berikut.

SCENE LAMA:
{last['ai']}

PERBAIKAN USER:
{user_revision}

ATURAN:
- jangan ubah karakter
- jangan ubah lokasi tiba‑tiba
- jangan ubah waktu tiba‑tiba
- dialog realistis
- jangan meta knowledge NPC
- pertahankan inti adegan
"""

    await update.message.reply_text(f"🔄 Regenerasi dengan `{model_name}`…", parse_mode="Markdown")
    ai_text, model_used = await generate(prompt, model_name)

    # Bersihkan flags regen
    context.user_data.pop("regen_scene", None)
    context.user_data.pop("regen_model", None)

    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate Lagi", callback_data="regen")]
    ]
    await update.message.reply_text(
        ai_text[:3500] + f"\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ------------------------------------------------------------------
# /replay – kirim seluruh story sebagai file .txt
# ------------------------------------------------------------------
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    archive = await get_full_story(query.from_user.id)
    if not archive:
        await query.message.reply_text("⚠️ Belum ada story.")
        return

    txt = "📖 FULL STORY REPLAY\n\n"
    for scene in archive:
        txt += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"TURN {scene['turn']}\n"
            f"USER: {scene['user']}\n"
            f"AI:   {scene['ai']}\n\n"
        )

    filename = f"story_{query.from_user.id}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(txt)

    with open(filename, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=filename,
            caption="📖 Replay story berhasil dibuat.",
        )

# ------------------------------------------------------------------
# /retry – ulangi prompt terakhir
# ------------------------------------------------------------------
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    prompt = await get_last_prompt(user_id)
    if not prompt:
        await query.message.reply_text("⚠️ Tidak ada prompt terakhir.")
        return

    # Ambil model yang sedang dipilih
    state = await get_full_state(user_id)
    selected_model = state["metadata"].get("selected_model", "gemini-2.5-flash")

    await query.message.reply_text("🔄 Mengulang proses terakhir...")
    ai_text, model_used = await generate(prompt, selected_model)

    await query.message.reply_text(ai_text[:3500] + f"\n\n🤖 {model_used}")

# ------------------------------------------------------------------
# /import – disediakan di import_handler.py
# ------------------------------------------------------------------
# (import_handler.register_import(app) dipanggil di `main()`)

# ------------------------------------------------------------------
# Message router
# ------------------------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "regen_scene" in context.user_data:
        await rewrite(update, context)
    else:
        await chat_engine(update, context)

# ------------------------------------------------------------------
# Error handler (debug)
# ------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("❌ Unhandled error:", exc_info=context.error)

# ------------------------------------------------------------------
# Set /commands menu di Telegram
# ------------------------------------------------------------------
async def set_bot_commands(app):
    commands = [
        BotCommand("start",   "🏠 Mulai / Pilih genre"),
        BotCommand("model",   "🤖 Pilih model AI"),
        BotCommand("replay",  "📖 Replay story (file txt)"),
        BotCommand("regen",   "🔁 Regenerate scene"),
        BotCommand("import",  "📂 Upload story .txt"),
        BotCommand("retry",   "🔂 Ulangi prompt terakhir"),
    ]
    await app.bot.set_my_commands(commands)

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # ---- COMMAND HANDLERS -------------------------------------------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_menu))
    app.add_handler(CommandHandler("replay", replay))
    app.add_handler(CommandHandler("regen", regenerate))
    app.add_handler(CommandHandler("retry", retry_last))

    # ---- CALLBACK HANDLERS ------------------------------------------------
    app.add_handler(CallbackQueryHandler(select_genre, pattern=r"^genre_"))
    app.add_handler(CallbackQueryHandler(select_model, pattern=r"^model_"))
    app.add_handler(CallbackQueryHandler(select_regen_model, pattern=r"^regenmodel_"))
    app.add_handler(CallbackQueryHandler(replay, pattern=r"^replay$"))
    app.add_handler(CallbackQueryHandler(retry_last, pattern=r"^retry_last$"))

    # ---- MESSAGE HANDLER --------------------------------------------------
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # ---- IMPORT HANDLER ---------------------------------------------------
    from import_handler import register_import
    register_import(app)

    # ---- ERROR ------------------------------------------------------------
    app.add_error_handler(error_handler)

    # ---- SET COMMAND MENU -------------------------------------------------
    app.post_init = set_bot_commands

    log.info("✅ Bot RUNNING")
    app.run_polling(poll_interval=1, timeout=30, drop_pending_updates=True)


if __name__ == "__main__":
    main()
