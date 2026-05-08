import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
        [InlineKeyboardButton("Romcom", callback_data="romcom")],
        [InlineKeyboardButton("Adventure", callback_data="adventure")]
    ]

    await update.message.reply_text(
        "Pilih genre",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# CHAT ENGINE
# =========================
async def chat_engine(update: Update, context):

    user_id = update.effective_user.id
    user_msg = update.message.text

    data = await memory.get_user(user_id)

    if not data:
        return

    story = data.get("story")

    prompt = build_prompt(story, user_msg)

    ai_text, model = await generate(prompt)

    await memory.update_story(user_id, story, ai_text, user_msg)

    # 🔥 SIMPAN UNTUK REGENERATE
    await memory.set_last_scene(user_id, prompt, ai_text, story)

    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")]
    ]

    await update.message.reply_text(
        ai_text + f"\n\n🤖 {model}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# REGENERATE HANDLER
# =========================
async def regenerate(update: Update, context):

    query = update.callback_query
    await query.answer()

    last = await memory.get_last_scene(query.from_user.id)

    context.user_data["regen"] = last

    await query.message.reply_text(
        "Kirim revisi cerita (contoh: buat Nina lebih dingin, ubah adegan)"
    )


# =========================
# REWRITE MODE
# =========================
async def chat_engine_rewrite(update: Update, context):

    if "regen" not in context.user_data:
        return

    last = context.user_data["regen"]

    prompt = f"""
REWRITE SCENE

SCENE LAMA:
{last['ai_text']}

REVISI USER:
{update.message.text}

TULIS ULANG DENGAN KONSISTEN.
"""

    ai_text, model = await generate(prompt)

    context.user_data.pop("regen")

    await update.message.reply_text(ai_text + f"\n\n🤖 {model}")


# =========================
# MAIN
# =========================
def main():

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_engine))
    app.add_handler(CallbackQueryHandler(regenerate, pattern="regen"))

    print("BOT RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()
