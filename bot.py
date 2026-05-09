import asyncio

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import memory

from ai_engine import generate
from prompt_builder import build_prompt
from config import BOT_TOKEN, AVAILABLE_MODELS

from memory import (
    get_full_story,
    save_last_prompt,
    get_last_prompt
)

# =========================================================
# START
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    await memory.init_user(user_id)

    keyboard = [
        [
            InlineKeyboardButton(
                "Roman Komedi",
                callback_data="genre_romcom"
            )
        ],
        [
            InlineKeyboardButton(
                "Petualangan",
                callback_data="genre_adventure"
            )
        ]
    ]

    await update.message.reply_text(
        "Pilih genre cerita:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# PILIH GENRE
# =========================================================
async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    genre = query.data.split("_")[1]

    prompts = {

        "romcom": """
Romantis komedi dewasa realistis.

JANGAN:
- teleport lokasi
- ubah waktu tiba-tiba
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
"""
    }

    await memory.set_genre(
        query.from_user.id,
        genre,
        prompts[genre]
    )

    await query.edit_message_text(
        f"Genre dipilih: {genre}\n\nKirim premis cerita awal."
    )


# =========================================================
# MENU MODEL
# =========================================================
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = []

    for label, model_name in AVAILABLE_MODELS.items():

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"model_{model_name}"
            )
        ])

    await update.message.reply_text(
        "Pilih model AI:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# PILIH MODEL
# =========================================================
async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    model_name = query.data.replace(
        "model_",
        ""
    )

    await memory.users.update_one(
        {"_id": query.from_user.id},
        {
            "$set": {
                "selected_model": model_name
            }
        }
    )

    await query.edit_message_text(
        f"✅ Model aktif:\n\n{model_name}"
    )


# =========================================================
# CHAT ENGINE
# =========================================================
async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user_msg = update.message.text

    data = await memory.get_user(user_id)

    if not data:
        return

    if data.get("state") != "STORY":
        return

    story = data["story"]

    # build prompt
    prompt = build_prompt(
        story,
        user_msg
    )

    # save last prompt
    await save_last_prompt(
        user_id,
        prompt
    )

    try:

        selected_model = data.get(
            "selected_model",
            "gemini-2.5-flash"
        )

        print(f"TRY MODEL: {selected_model}")

        ai_text, model = await generate(
            prompt,
            selected_model
        )

        # fallback
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

        # save archive
        await memory.update_story(
            user_id,
            story,
            ai_text,
            user_msg
        )

        # save regenerate data
        await memory.set_last_scene(
            user_id,
            prompt,
            ai_text,
            story
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔁 Regenerate",
                    callback_data="regen"
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 Replay Story",
                    callback_data="replay"
                )
            ]
        ]

        safe_text = ai_text[:3500]

        await update.message.reply_text(
            safe_text + f"\n\n🤖 {model}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:

        print("CHAT ENGINE ERROR:", e)

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔁 Retry Last Prompt",
                    callback_data="retry_last"
                )
            ]
        ]

        await update.message.reply_text(
            "Terjadi error saat proses AI.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# REGENERATE
# =========================================================
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    last = await memory.get_last_scene(
        query.from_user.id
    )

    context.user_data["regen"] = last

    await query.message.reply_text(
        "Kirim revisi cerita:"
    )


# =========================================================
# REWRITE
# =========================================================
async def rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if "regen" not in context.user_data:
        return

    last = context.user_data["regen"]

    prompt = f"""
REWRITE CERITA.

CERITA LAMA:
{last['ai_text']}

PERBAIKAN USER:
{update.message.text}

ATURAN:
- jangan ubah lokasi tiba-tiba
- jangan ubah waktu tiba-tiba
- pertahankan karakter
- transisi realistis
"""

    ai_text, model = await generate(prompt)

    context.user_data.pop("regen")

    await update.message.reply_text(
        ai_text[:3500] + f"\n\n🤖 {model}"
    )


# =========================================================
# REPLAY STORY
# =========================================================
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    archive = await get_full_story(
        query.from_user.id
    )

    if not archive:

        await query.message.reply_text(
            "Belum ada story."
        )

        return

    text = "📖 FULL STORY REPLAY\n\n"

    for scene in archive:

        text += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"TURN: {scene['turn']}\n\n"

            f"USER:\n"
            f"{scene['user']}\n\n"

            f"AI:\n"
            f"{scene['ai']}\n\n"
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


# =========================================================
# RETRY LAST PROMPT
# =========================================================
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE):

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

    data = await memory.get_user(user_id)

    selected_model = data.get(
        "selected_model",
        "gemini-2.5-flash"
    )

    ai_text, model = await generate(
        prompt,
        selected_model
    )

    await query.message.reply_text(
        ai_text[:3500] + f"\n\n🤖 {model}"
    )


# =========================================================
# ERROR HANDLER
# =========================================================
async def error_handler(update, context):

    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================
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
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("model", model_menu)
    )

    # CALLBACKS
    app.add_handler(
        CallbackQueryHandler(
            select_genre,
            pattern="^genre_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            select_model,
            pattern="^model_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            regenerate,
            pattern="^regen$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            replay,
            pattern="^replay$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            retry_last,
            pattern="^retry_last$"
        )
    )

    # MESSAGE
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            rewrite
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat_engine
        )
    )

    app.add_error_handler(error_handler)

    print("BOT RUNNING")

    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    main()
