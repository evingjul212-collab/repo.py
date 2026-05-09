# -------------------------------------------------
# File: bot.py
# -------------------------------------------------

import asyncio
import logging
from pathlib import Path

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

# ----------------------------------------------------------------------
# IMPORT INTERNAL MODULES  (pastikan modul‑modul ini ada di repo Anda)
# ----------------------------------------------------------------------
import memory                       # wrapper MongoDB / state handling
from ai_engine import generate      # pemanggilan model Gemini / Gemma dsb.
from prompt_builder import build_prompt
from config import BOT_TOKEN, AVAILABLE_MODELS

# ----------------------------------------------------------------------
# LOGGING CONFIG
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# -------------------------- COMMAND HANDLERS -------------------------
# ----------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan menu genre untuk memulai cerita."""
    user_id = update.effective_user.id

    # Inisialisasi data user (buat dokumen kosong bila belum ada)
    await memory.init_user(user_id)

    keyboard = [
        [
            InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")
        ],
        [
            InlineKeyboardButton("Petualangan", callback_data="genre_adventure")
        ],
    ]

    await update.message.reply_text(
        "Pilih genre cerita:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan genre + prompt template ke database."""
    query = update.callback_query
    await query.answer()

    genre = query.data.split("_")[1]

    prompts = {
        "romcom": """
Romantis komedi dewasa realistis.

JANGAN:
- teleport lokasi
- ubah waktu tiba‑tiba
- karakter tahu isi pikiran lawan bicara
- karakter berbicara mustahil dari jarak jauh
- meta‑knowledge NPC

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
- meta‑knowledge NPC

WAJIB:
- transisi adegan jelas
- lokasi konsisten
- waktu konsisten
""",
    }

    await memory.set_genre(query.from_user.id, genre, prompts[genre])

    await query.edit_message_text(
        f"✅ Genre dipilih: *{genre}*\n\nKirim premis cerita awal.",
        parse_mode="Markdown",
    )


# -------------------------------------------------
# MODEL MENU
# -------------------------------------------------
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan semua model yang tersedia (di config AVAILABLE_MODELS)."""
    keyboard = []

    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [
                InlineKeyboardButton(label, callback_data=f"model_{model_name}"),
            ]
        )

    await update.message.reply_text(
        "Pilih model AI:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan model terpilih ke user‑state."""
    query = update.callback_query
    await query.answer()

    model_name = query.data.replace("model_", "")

    await memory.users.update_one(
        {"_id": query.from_user.id},
        {"$set": {"selected_model": model_name}},
    )

    await query.edit_message_text(f"✅ Model aktif:\n\n`{model_name}`", parse_mode="Markdown")


# -------------------------------------------------
# REPLAY STORY (export menjadi file .txt)
# -------------------------------------------------
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kirim kembali seluruh story dalam bentuk file .txt."""
    query = update.callback_query
    await query.answer()

    archive = await memory.get_full_story(query.from_user.id)

    if not archive:
        await query.message.reply_text("📂 Belum ada story untuk user ini.")
        return

    # Bangun teks replay
    text = "📖 **FULL STORY REPLAY**\n\n"
    for scene in archive:
        text += (
            "━━━━━━━━━━━━━━━━━━\n"
            f"TURN: {scene['turn']}\n\n"
            f"USER:\n{scene['user']}\n\n"
            f"AI:\n{scene['ai']}\n\n"
        )

    # Simpan sementara ke file
    filename = f"story_{query.from_user.id}.txt"
    path = Path("/tmp") / filename
    path.write_text(text, encoding="utf‑8")

    # Kirim file
    with open(path, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=filename,
            caption="📄 Replay story berhasil dibuat.",
        )

    # Hapus file sementara (opsional)
    try:
        path.unlink()
    except Exception:
        pass


# -------------------------------------------------
# IMPORT STORY (open dari file .txt)
# -------------------------------------------------
async def import_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Perintah /import – memberi instruksi untuk meng‑upload file .txt.
    Setelah file di‑upload, handler `handle_story_file` (di bawah) akan
    memprosesnya dan meng‑set state ke STORY.
    """
    await update.message.reply_text(
        "📂 *Open story from txt*\n\n"
        "Silakan kirim file *.txt* yang berisi cerita yang ingin Anda "
        "lanjutkan. Bot akan meng‑import isinya dan mengatur state ke "
        "`STORY`, sehingga Anda dapat langsung melanjutkan percakapan.\n\n"
        "_Catatan: file hanya boleh berukuran ≤ 5 MB dan berformat teks._",
        parse_mode="Markdown",
    )


async def handle_story_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Dijalankan ketika user meng‑upload file .txt setelah memanggil /import.
    File dibaca, disimpan ke DB, dan status di‑set menjadi STORY.
    """
    document = update.message.document

    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text(
            "❌ Hanya file *.txt* yang dapat di‑import."
        )
        return

    # Unduh file ke /tmp
    file_path = await document.get_file()
    local_path = Path("/tmp") / document.file_name
    await file_path.download_to_drive(custom_path=str(local_path))

    # Baca isi
    try:
        story_text = local_path.read_text(encoding="utf‑8")
    except Exception as e:
        logger.error("Baca file gagal: %s", e)
        await update.message.reply_text("❌ Gagal membaca file .txt.")
        return
    finally:
        # Hapus file lokal
        try:
            local_path.unlink()
        except Exception:
            pass

    # Simpan ke DB – disimpan sebagai satu “scene” saja (turn=0)
    user_id = update.effective_user.id
    await memory.init_user(user_id)          # pastikan dokumen ada

    # Kosongkan story lama (opsional) atau append – di sini saya reset
    await memory.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY",
                "selected_model": "gemini-2.5-flash",   # default, bisa di‑ubah lewat /model
                "story": [],
            }
        },
    )

    # Simpan scene pertama (isi lengkap file)
    await memory.update_story(
        user_id,
        previous_story="",          # tidak ada story sebelumnya
        ai_text=story_text,
        user_msg="(imported story)",
    )

    await update.message.reply_text(
        "✅ Story berhasil di‑import! Sekarang Anda dapat melanjutkan "
        "percakapan dengan mengirim pesan teks biasa.",
    )


# -------------------------------------------------
# CHAT ENGINE (mengirim prompt ke AI)
# -------------------------------------------------
async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Proses percakapan utama.  Hanya dijalankan bila user berada dalam
    state `STORY`.
    """
    user_id = update.effective_user.id
    user_msg = update.message.text

    data = await memory.get_user(user_id)
    if not data or data.get("state") != "STORY":
        # Jika belum memulai story, abaikan
        return

    story = data["story"]

    # Buat prompt lengkap (story + user_msg)
    prompt = build_prompt(story, user_msg)

    # Simpan prompt terakhir (untuk retry)
    await memory.save_last_prompt(user_id, prompt)

    try:
        selected_model = data.get("selected_model", "gemini-2.5-flash")
        logger.info("TRY MODEL: %s", selected_model)

        ai_text, model_used = await generate(prompt, selected_model)

        # Jika generate mengembalikan fallback (misal semua model error)
        if model_used == "fallback":
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔁 Retry Last Prompt", callback_data="retry_last"
                    )
                ]
            ]
            await update.message.reply_text(
                ai_text, reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        # Simpan ke archive
        await memory.update_story(user_id, story, ai_text, user_msg)

        # Simpan data regen (untuk /regen)
        await memory.set_last_scene(user_id, prompt, ai_text, story)

        # Tombol aksi setelah AI menjawab
        keyboard = [
            [
                InlineKeyboardButton("🔁 Regenerate", callback_data="regen"),
            ],
            [
                InlineKeyboardButton("📖 Replay Story", callback_data="replay"),
            ],
        ]

        safe_text = ai_text[:3500]  # batas Telegram
        await update.message.reply_text(
            f"{safe_text}\n\n🤖 {model_used}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as exc:
        logger.exception("CHAT ENGINE ERROR")
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔁 Retry Last Prompt", callback_data="retry_last"
                )
            ]
        ]
        await update.message.reply_text(
            "⚠️ Terjadi error saat memanggil AI.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# -------------------------------------------------
# REGENERATE
# -------------------------------------------------
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan pilihan model untuk regenerate scene terakhir."""
    query = update.callback_query
    await query.answer()

    last_scene = await memory.get_last_scene(query.from_user.id)
    if not last_scene:
        await query.message.reply_text("❌ Tidak ada scene terakhir.")
        return

    # Simpan data scene di user_data supaya dapat dipanggil kembali
    context.user_data["regen_scene"] = last_scene

    # Pilih model (sama seperti menu model)
    keyboard = []
    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"regenmodel_{model_name}"
                )
            ]
        )

    await query.message.reply_text(
        "Pilih model untuk regenerate:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_regen_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan model yang dipilih untuk proses regenerate."""
    query = update.callback_query
    await query.answer()

    model_name = query.data.replace("regenmodel_", "")
    context.user_data["regen_model"] = model_name

    await query.message.reply_text(
        "Kirim revisi/perbaikan cerita (contoh: \"jangan pindah lokasi\")."
    )


async def rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gunakan prompt revisi + model terpilih untuk menghasilkan scene baru."""
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
- jangan ubah karakter
- jangan ubah lokasi tiba‑tiba
- jangan ubah waktu tiba‑tiba
- dialog realistis
- jangan meta‑knowledge NPC
- pertahankan inti adegan
"""

    await update.message.reply_text(f"🔄 Regenerate pakai `{model_name}`...", parse_mode="Markdown")

    ai_text, model_used = await generate(prompt, model_name)

    # Bersihkan state regen
    context.user_data.pop("regen_scene", None)
    context.user_data.pop("regen_model", None)

    keyboard = [
        [
            InlineKeyboardButton("🔁 Regenerate Lagi", callback_data="regen")
        ]
    ]

    await update.message.reply_text(
        f"{ai_text[:3500]}\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# -------------------------------------------------
# RETRY LAST PROMPT
# -------------------------------------------------
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ulangi proses terakhir (biasanya dipanggil saat fallback)."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    prompt = await memory.get_last_prompt(user_id)

    if not prompt:
        await query.message.reply_text("❌ Tidak ada prompt terakhir.")
        return

    await query.message.reply_text("🔁 Mengulang proses terakhir...")

    user_data = await memory.get_user(user_id)
    selected_model = user_data.get("selected_model", "gemini-2.5-flash")

    ai_text, model_used = await generate(prompt, selected_model)

    await query.message.reply_text(f"{ai_text[:3500]}\n\n🤖 {model_used}")


# -------------------------------------------------
# MESSAGE ROUTER
# -------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Jika user sedang dalam mode *regen* (telah mengirim /regen),
    pertama‑tama panggil `rewrite`; kalau tidak, jalankan `chat_engine`.
    """
    if "regen_scene" in context.user_data:
        await rewrite(update, context)
    else:
        await chat_engine(update, context)


# -------------------------------------------------
# ERROR HANDLER
# -------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log semua error yang tidak tertangani."""
    logger.error("Exception while handling update:", exc_info=context.error)


# -------------------------------------------------
# SET BOT COMMANDS (menu di Telegram)
# -------------------------------------------------
async def set_bot_commands(app: Application) -> None:
    commands = [
        BotCommand("start", "🏠 Menu Utama"),
        BotCommand("model", "🤖 Pilih Model AI"),
        BotCommand("replay", "📖 Replay Story (file txt)"),
        BotCommand("regen", "🔁 Regenerate Scene"),
        BotCommand("import", "📂 Open story from txt"),
    ]
    await app.bot.set_my_commands(commands)


# -------------------------------------------------
# MAIN – inisialisasi aplikasi
# -------------------------------------------------
def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # ---------- COMMAND HANDLERS ----------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_menu))
    app.add_handler(CommandHandler("replay", replay))
    app.add_handler(CommandHandler("regen", regenerate))
    app.add_handler(CommandHandler("import", import_cmd))

    # ---------- CALLBACK HANDLERS ----------
    app.add_handler(
        CallbackQueryHandler(select_genre, pattern="^genre_")
    )
    app.add_handler(
        CallbackQueryHandler(select_model, pattern="^model_")
    )
    app.add_handler(
        CallbackQueryHandler(regenerate, pattern="^regen$")
    )
    app.add_handler(
        CallbackQueryHandler(select_regen_model, pattern="^regenmodel_")
    )
    app.add_handler(
        CallbackQueryHandler(replay, pattern="^replay$")
    )
    app.add_handler(
        CallbackQueryHandler(retry_last, pattern="^retry_last$")
    )

    # ---------- MESSAGE HANDLERS ----------
    # 1. Text (chat normal)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_router)
    )
    # 2. Document .txt – import story
    app.add_handler(
        MessageHandler(filters.Document.FileExtension("txt") & ~filters.COMMAND, handle_story_file)
    )

    # ---------- ERROR ----------
    app.add_error_handler(error_handler)

    # ---------- POST‑INIT (set menu) ----------
    app.post_init = set_bot_commands

    logger.info("🚀 Bot RUNNING")
    app.run_polling(
        poll_interval=1,
        timeout=30,
        drop_pending_updates=True,
    )


# -------------------------------------------------
# ENTRY POINT
# -------------------------------------------------
if __name__ == "__main__":
    main()
