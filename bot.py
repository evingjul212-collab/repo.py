import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from memory import get_full_story
from memory import save_last_prompt, get_last_prompt
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

import memory
from ai_engine import generate
from prompt_builder import build_prompt
from config import BOT_TOKEN


# =========================
# START
# =========================
async def start(update: Update, context):

    await memory.init_user(update.effective_user.id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan", callback_data="genre_adventure")]
    ]

    await update.message.reply_text(
        "Pilih genre:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# GENRE HANDLER (INI FIX UTAMA)
# =========================
async def select_genre(update: Update, context):

    query = update.callback_query
    await query.answer()

    genre = query.data.split("_")[1]

    prompts = {
        "romcom": "Romantis komedi ringan",
        "adventure": "Petualangan dramatis"
    }

    await memory.set_genre(
        query.from_user.id,
        genre,
        prompts[genre]
    )

    await query.edit_message_text(
        f"Genre dipilih: {genre}\nKetik cerita awal."
    )


# =========================
# CHAT ENGINE
# =========================
async def chat_engine(update: Update, context):

    user_id = update.effective_user.id
    msg = update.message.text

    data = await memory.get_user(user_id)

    if not data or data.get("state") != "STORY":
        return

    story = data["story"]

    prompt = build_prompt(story, msg)
    await save_last_prompt(user_id, prompt)

    ai_text, model = await generate(prompt)

    await memory.update_story(
    user_id,
    story,
    ai_text,
    msg,
    prompt
)

    await memory.set_last_scene(user_id, prompt, ai_text, story)

    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")],
        [InlineKeyboardButton("📖 Replay Story", callback_data="replay")]
        
    ]

    await update.message.reply_text(
        ai_text + f"\n\n🤖 {model}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# REGENERATE
# =========================
async def regenerate(update: Update, context):

    query = update.callback_query
    await query.answer()

    last = await memory.get_last_scene(query.from_user.id)

    context.user_data["regen"] = last

    await query.message.reply_text(
        "Kirim revisi cerita:"
    )

# =========================
# REWRITE MODE
# =========================
async def rewrite(update: Update, context):

    if "regen" not in context.user_data:
        return

    last = context.user_data["regen"]

    prompt = f"""
REWRITE:
{last['ai_text']}

REVISI:
{update.message.text}
"""

    ai_text, model = await generate(prompt)

    if model == "fallback":

        keyboard = [
        [
            InlineKeyboardButton(
                "🔁 Retry Last Prompt",
                callback_data="retry_last"
            )
        ]
    ]

        await update.message.reply_text(
        ai_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return

    context.user_data.pop("regen")

    await update.message.reply_text(ai_text + f"\n\n🤖 {model}")
#====================================================
async def replay(update: Update, context):

    query = update.callback_query
    await query.answer()

    archive = await get_full_story(query.from_user.id)

    if not archive:
        await query.message.reply_text("Belum ada story.")
        return

    text = "📖 FULL STORY REPLAY\n\n"

    for scene in archive:
        text += (
            f"━━━━━━━━━━\n"
            f"Turn: {scene['turn']}\n"
            f"User: {scene['user']}\n"
            f"AI: {scene['ai']}\n\n"
        )

        await query.message.reply_text(text[:3500])
#==================================
async def error_handler(update, context):
    print("ERROR:", context.error)       
#================
async def retry_last(update: Update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    prompt = await get_last_prompt(user_id)

    if not prompt:

        await query.message.reply_text(
            "Tidak ada prompt terakhir."
        )

        return

    await query.message.reply_text(
        "🔄 Mengulang proses terakhir..."
    )

    ai_text, model = await generate(prompt)

    await query.message.reply_text(
        ai_text + f"\n\n🤖 {model}"
    )
# =========================
# MAIN
# =========================
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

    app.add_handler(CommandHandler("start", start))

    # genre
    app.add_handler(
        CallbackQueryHandler(select_genre, pattern="^genre_")
    )

    # regenerate
    app.add_handler(
        CallbackQueryHandler(regenerate, pattern="regen")
    )

    # replay
    app.add_handler(
        CallbackQueryHandler(replay, pattern="replay")
    )

    # chat
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, chat_engine)
    )
    app.add_handler(
    CallbackQueryHandler(
        retry_last,
        pattern="retry_last"
        )
    )
    print("BOT RUNNING")
    app.add_error_handler(error_handler)
    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True
        )
if __name__ == "__main__":
    main()
