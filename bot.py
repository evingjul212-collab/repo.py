# bot.py
import logging
import asyncio
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
import memory
from ai_engine import generate
from prompt_builder import build_prompt
from config import BOT_TOKEN, AVAILABLE_MODELS
from memory import (
    get_full_story,
    save_last_prompt,
    get_last_prompt,
)

# ----------------------------------------------------------------------
# LOGGING
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# START
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await memory.init_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan", callback_data="genre_adventure")],
    ]
    await update.message.reply_text(
        "Pilih genre cerita:", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ----------------------------------------------------------------------
# SELECT GENRE
# ----------------------------------------------------------------------
async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    genre = query.data.split("_")[1]

    prompts = {
        "romcom": """
Romantis komedi dewasa realistis.
JANGAN: teleport, ubah waktu tiba‑tiba, meta‑knowledge NPC.
WAJIB: lokasi, waktu, dialog natural.
""",
        "adventure": """
Petualangan dramatis realistis.
JANGAN: teleport, lompat waktu, meta‑knowledge NPC.
WAJIB: lokasi konsisten, transisi adegan jelas.
""",
    }

    await memory.set_genre(query.from_user.id, genre, prompts[genre])
    await query.edit_message_text(
        f"Genre dipilih: {genre}\n\nKirim premis cerita awal."
    )

# ----------------------------------------------------------------------
# MODEL MENU
# ----------------------------------------------------------------------
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"model_{model_name}")]
        )
    await update.message.reply_text(
        "Pilih model AI:", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ----------------------------------------------------------------------
# SELECT MODEL
# ----------------------------------------------------------------------
async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    model_name = query.data.removeprefix("model_")
    await memory.users.update_one(
        {"_id": query.from_user.id},
        {"$set": {"selected_model": model_name}},
    )
    await query.edit_message_text(f"✅ Model aktif:\n\n{model_name}")

# ----------------------------------------------------------------------
# CHAT ENGINE
# ----------------------------------------------------------------------
async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_msg = update.message.text
    data = await memory.get_user(user_id)
    if not data or data.get("state") != "STORY":
        return

    story = data["story"]
    prompt = build_prompt(story, user_msg)

    await save_last_prompt(user_id, prompt)

    try:
        selected_model = data.get("selected_model", "gemini-2.5-flash")
        ai_text, model_used = await generate(prompt, selected_model)

        # Simpan ke DB
        await memory.update_story(user_id, story, ai_text, user_msg)
        await memory.set_last_scene(user_id, prompt, ai_text, story)

        # Tombol aksi
        keyboard = [
            [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")],
            [InlineKeyboardButton("📖 Replay Story", callback_data="replay")],
        ]

        await update.message.reply_text(
            ai_text[:3500] + f"\n\n🤖 {model_used}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        log.exception("chat_engine error")
        await update.message.reply_text(
            "⚠️ Terjadi error saat proses AI. Coba lagi."
        )

# ----------------------------------------------------------------------
# REGENERATE
# ----------------------------------------------------------------------
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    last_scene = await memory.get_last_scene(query.from_user.id)
    if not last_scene:
        await query.message.reply_text("❌ Tidak ada scene terakhir.")
        return

    context.user_data["regen_scene"] = last_scene
    # Pilih model untuk regenerate
    keyboard = []
    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"regenmodel_{model_name}")]
        )
    await query.message.reply_text(
        "Pilih model untuk regenerate:", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ----------------------------------------------------------------------
# SELECT REGEN MODEL
# ----------------------------------------------------------------------
async def select_regen_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    model_name = query.data.removeprefix("regenmodel_")
    context.user_data["regen_model"] = model_name
    await query.message.reply_text(
        "Kirim revisi/perbaikan cerita (contoh: “jangan pindah lokasi”)."
    )

# ----------------------------------------------------------------------
# REWRITE (setelah user mengirim revisi)
# ----------------------------------------------------------------------
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
{last['ai_text']}

PERBAIKAN USER:
{user_revision}

ATURAN:
- jangan ubah karakter/ lokasi / waktu tiba‑tiba
- dialog realistis, tidak meta‑knowledge
- pertahankan inti adegan
"""

    await update.message.reply_text(f"🔄 Regenerate pakai: {model_name}")
    ai_text, model_used = await generate(prompt, model_name)

    # bersihkan state regen
    context.user_data.pop("regen_scene", None)
    context.user_data.pop("regen_model", None)

    keyboard = [[InlineKeyboardButton("🔁 Regenerate Lagi", callback_data="regen")]]
    await update.message.reply_text(
        ai_text[:3500] + f"\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ----------------------------------------------------------------------
# MESSAGE ROUTER
# ----------------------------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "regen_scene" in context.user_data:
        await rewrite(update, context)
    else:
        await chat_engine(update, context)

# ----------------------------------------------------------------------
# REPLAY STORY (kirim file txt)
# ----------------------------------------------------------------------
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    archive = await get_full_story(query.from_user.id)
    if not archive:
        await query.message.reply_text("Belum ada story.")
        return

    text = "📖 FULL STORY REPLAY\n\n"
    for scene in archive:
        text += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"TURN: {scene['turn']}\n"
            f"USER: {scene['user']}\n"
            f"AI: {scene['ai']}\n"
        )

    filename = f"story_{query.from_user.id}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)

    with open(filename, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=filename,
            caption="📖 Replay story berhasil dibuat."
        )

# ----------------------------------------------------------------------
# RETRY LAST PROMPT
# ----------------------------------------------------------------------
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    prompt = await get_last_prompt(user_id)
    if not prompt:
        await query.message.reply_text("Tidak ada prompt terakhir.")
        return
    await query.message.reply_text("🔄 Mengulang proses terakhir...")

    data = await memory.get_user(user_id)
    selected_model = data.get("selected_model", "gemini-2.5-flash")
    ai_text, model_used = await generate(prompt, selected_model)
    await query.message.reply_text(ai_text[:3500] + f"\n\n🤖 {model_used}")

# ----------------------------------------------------------------------
# ERROR HANDLER
# ----------------------------------------------------------------------
async def error_handler(update, context):
    log.exception("Telegram error")
    if update:
        await update.message.reply_text("⚠️ Terjadi error internal.")

# ----------------------------------------------------------------------
# SET BOT COMMANDS
# ----------------------------------------------------------------------
async def set_bot_commands(app):
    commands = [
        BotCommand("start", "🏠 Menu Utama"),
        BotCommand("model", "🤖 Pilih Model AI"),
        BotCommand("replay", "📖 Replay Story"),
        BotCommand("regen", "🔁 Regenerate Scene"),
        BotCommand("import", "📂 Buka file story (.txt)"),
    ]
    await app.bot.set_my_commands(commands)

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
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

    # COMMANDS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_menu))
    app.add_handler(CommandHandler("import", lambda u, c: None))  # placeholder, di‑register di import_handler

    # CALLBACKS
    app.add_handler(CallbackQueryHandler(select_genre, pattern="^genre_"))
    app.add_handler(CallbackQueryHandler(select_model, pattern="^model_"))
    app.add_handler(CallbackQueryHandler(regenerate, pattern="^regen$"))
    app.add_handler(CallbackQueryHandler(select_regen_model, pattern="^regenmodel_"))
    app.add_handler(CallbackQueryHandler(replay, pattern="^replay$"))
    app.add_handler(CallbackQueryHandler(retry_last, pattern="^retry_last$"))

    # MESSAGES
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    # IMPORT HANDLER (file .txt)
    from import_handler import register_import
    register_import(app)

    # ERRORS
    app.add_error_handler(error_handler)

    # SET MENU AFTER start
    app.post_init = set_bot_commands

    print("✅ Bot RUNNING")
    app.run_polling(poll_interval=1, timeout=30, drop_pending_updates=True)

if __name__ == "__main__":
    main()
