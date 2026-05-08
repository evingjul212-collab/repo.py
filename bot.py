import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from config import BOT_TOKEN
import memory
from ai_engine import generate
from prompt_builder import build_prompt


# =========================================================
# START
# =========================================================

async def start(update: Update, context):

    user_id = update.effective_user.id

    await memory.init_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi 😂", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan 🗺️", callback_data="genre_adventure")],
        [InlineKeyboardButton("Dewasa 🔥", callback_data="genre_mature")]
    ]

    await update.message.reply_text(
        "🎬 AI Story Engine v2\nPilih genre:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# GENRE SELECT
# =========================================================

async def select_genre(update: Update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    genre = query.data.split("_")[1]

    prompts = {
        "romcom": "Romantis komedi ringan natural.",
        "adventure": "Petualangan dramatis realistis.",
        "mature": "Cerita emosional serius."
    }

    await memory.set_genre(user_id, genre, prompts[genre])

    await query.edit_message_text(
        f"Genre {genre.upper()} aktif.\nKirim premis cerita."
    )


# =========================================================
# CHAT ENGINE (CORE LOOP)
# =========================================================

async def chat_engine(update: Update, context):

    user_id = update.effective_user.id
    user_msg = update.message.text

    data = await memory.get_story(user_id)

    if not data:
        await update.message.reply_text("Ketik /start dulu.")
        return

    if data.get("state") != "STORY_ONGOING":
        await update.message.reply_text("Pilih genre dulu (/start).")
        return

    story = data["story"]

    # build prompt structured
    prompt = build_prompt(story, user_msg)

    # AI generate
    ai_text, model = await generate(prompt)

    # update memory
    await memory.update_story(user_id, story, ai_text, user_msg)

    # send response
    final = f"{ai_text}\n\n🤖 {model}"

    await update.message.reply_text(final)


# =========================================================
# MAIN
# =========================================================

def main():

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(select_genre))
    app.add_handler(MessageHandler(filters.TEXT, chat_engine))

    print("AI STORY ENGINE v2 RUNNING")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
