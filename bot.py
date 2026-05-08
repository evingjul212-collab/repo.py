import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from memory import get_full_story
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

    ai_text, model = await generate(prompt)

    await memory.update_story(user_id, story, ai_text, msg)

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

    await query.message.reply_text(text[:3500])async def replay(update: Update, context):

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

# =========================
# MAIN
# =========================
def main():

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # 🔥 GENRE WAJIB INI
    app.add_handler(CallbackQueryHandler(select_genre, pattern="^genre_"))

    # 🔥 REGEN
    app.add_handler(CallbackQueryHandler(regenerate, pattern="regen"))

    # CHAT
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_engine))

    print("BOT RUNNING")
    app.run_polling(drop_pending_updates=True)
    
    app.add_handler(
    CallbackQueryHandler(replay, pattern="replay")
)

if __name__ == "__main__":
    main()
