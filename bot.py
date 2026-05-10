# -------------------------------------------------
# File: bot.py
# -------------------------------------------------

import asyncio
import logging
from pathlib import Path
import re

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
# INTERNAL MODULES  (pastikan file‑file ini ada di repo Anda)
# ----------------------------------------------------------------------
import memory                       # wrapper MongoDB / state handling
from ai_engine import generate      # pemanggilan model Gemini / Gemma dsb.
from prompt_builder import build_prompt
from config import BOT_TOKEN, AVAILABLE_MODELS

# ----------------------------------------------------------------------
# LOGGING
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
    """Menu utama – pilih genre cerita."""
    user_id = update.effective_user.id
    await memory.init_user(user_id)

    keyboard = [
        [InlineKeyboardButton("Roman Komedi", callback_data="genre_romcom")],
        [InlineKeyboardButton("Petualangan", callback_data="genre_adventure")],
    ]

    await update.message.reply_text(
        "📚 *Pilih genre cerita*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def select_genre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan genre & template prompt ke DB."""
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
        f"✅ *Genre* dipilih: `{genre}`\n\nKirim premis cerita awal.",
        parse_mode="Markdown",
    )


# ----------------------------------------------------------------------
# MODEL MENU
# ----------------------------------------------------------------------
async def model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan semua model yang terdaftar di config."""
    keyboard = []
    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"model_{model_name}")]
        )

    await update.message.reply_text(
        "🤖 *Pilih model AI*:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan pilihan model ke user‑state."""
    query = update.callback_query
    await query.answer()

    model_name = query.data.replace("model_", "")

    await memory.users.update_one(
        {"_id": query.from_user.id},
        {"$set": {"selected_model": model_name}},
    )

    await query.edit_message_text(
        f"✅ Model aktif: `{model_name}`", parse_mode="Markdown"
    )


# ----------------------------------------------------------------------
# REPLAY STORY (ekspor menjadi file .txt)
# ----------------------------------------------------------------------
async def replay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kirim seluruh story dalam bentuk file .txt."""
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
    # (opsional) bersihkan file temporer
    try:
        path.unlink()
    except Exception:
        pass


# ----------------------------------------------------------------------
# IMPORT STORY (buka dari file .txt)
# ----------------------------------------------------------------------
async def import_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Perintah /import – memberi instruksi untuk meng‑upload file *.txt*.
    Setelah file di‑upload, handler `handle_story_file` akan memprosesnya.
    """
    await update.message.reply_text(
        "📂 *Open story from txt*\n\n"
        "Silakan kirim file *.txt* (hasil dari `/replay`). "
        "Bot akan membaca seluruh isi, menyimpannya, dan menampilkan "
        "scene terakhir sebagai konfirmasi.\n\n"
        "_Catatan: file hanya boleh berukuran ≤ 5 MB dan berformat teks._",
        parse_mode="Markdown",
    )


# -------------------------------------------------
# `handle_story_file`)
# -------------------------------------------------
async def handle_story_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    1️⃣ Unduh file .txt ke /tmp
    2️⃣ Baca isinya
    3️⃣ Pecah menjadi scene (delimiter “━━━━━━━━━━━━━━━━━━”)
    4️⃣ Simpan setiap scene ke DB dengan field turn, user, ai
    5️⃣ Tampilkan scene terakhir sebagai konfirmasi
    """
    document = update.message.document

    # ---- validasi ekstensi ----
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Hanya file *.txt* yang dapat di‑import.")
        return

    # ---- unduh ----
    file_obj = await document.get_file()
    local_path = Path("/tmp") / document.file_name
    await file_obj.download_to_drive(custom_path=str(local_path))

    # ---- baca ----
    try:
        content = local_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Gagal membaca file txt: %s", exc)
        await update.message.reply_text("❌ Gagal membaca file .txt.")
        return
    finally:
        # bersihkan file lokal
        try:
            local_path.unlink()
        except Exception:
            pass

    if not content.strip():
        await update.message.reply_text("⚠️ File kosong. Tidak ada cerita yang di‑import.")
        return

    # ---- 1. Pecah menjadi scene ----
    raw_scenes = re.split(r"━━━━━━━━━━━━━━━━━━", content)
    scenes = [s.strip() for s in raw_scenes if s.strip()]

    # ---- 2. Reset story lama & buat dokumen user bila belum ada ----
    user_id = update.effective_user.id
    await memory.init_user(user_id)                     # buat dokumen bila belum ada
    await memory.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY",
                "selected_model": "gemini-2.5-flash",  # default, bisa di‑ubah lewat /model
                "story": [],                           # kosongkan dulu
                "genre": "imported",
                "prompt_template": "",                 # tidak dipakai lagi
            }
        },
    )

    # ---- 3. Simpan tiap scene ke DB ----
    turn_counter = 0
    for scene in scenes:
        # Ambil bagian USER & AI bila ada; kalau tidak, gunakan fallback.
        user_match = re.search(r"USER:\s*(.+?)(?=\nAI:|$)", scene, flags=re.S)
        ai_match   = re.search(r"AI:\s*(.+)", scene, flags=re.S)

        user_text = user_match.group(1).strip() if user_match else "(imported story)"
        ai_text   = ai_match.group(1).strip()   if ai_match   else ""

        await memory.users.update_one(
            {"_id": user_id},
            {
                "$push": {
                    "story": {
                        "turn": turn_counter,
                        "user": user_text,
                        "ai":   ai_text,
                    }
                }
            },
        )
        turn_counter += 1

    # ---- 4. Tampilkan scene terakhir (konfirmasi) ----
    last_scene = await memory.get_last_scene(user_id)

    if not last_scene:
        await update.message.reply_text("⚠️ Tidak ada scene yang berhasil di‑import.")
        return

    await update.message.reply_text(
        "✅ *Story berhasil di‑import!* Berikut scene terakhir yang akan menjadi titik "
        "awal percakapan:\n\n"
        f"*TURN {last_scene['turn']}*\n"
        f"*USER:* {last_scene['user'][:200]}\n"
        f"*AI:* {last_scene['ai'][:200]}",
        parse_mode="Markdown",
    )

    # Unduh file ke /tmp
    file_obj = await document.get_file()
    local_path = Path("/tmp") / document.file_name
    await file_obj.download_to_drive(custom_path=str(local_path))

    # Baca isi
    try:
        content = local_path.read_text(encoding="utf‑8")
    except Exception as e:
        logger.error("Gagal membaca file txt: %s", e)
        await update.message.reply_text("❌ Gagal membaca file .txt.")
        return
    finally:
        # Hapus file lokal (keamanan)
        try:
            local_path.unlink()
        except Exception:
            pass

    if not content.strip():
        await update.message.reply_text("⚠️ File kosong. Tidak ada story yang di‑import.")
        return

    # -------------------------------------------------
    # 1️⃣  Pecah menjadi scene
    # -------------------------------------------------
    # Delimiter yang dipakai di /replay adalah:  ━━━━━━━━━━━━━━━━━━
    raw_scenes = re.split(r"━━━━━━━━━━━━━━━━━━", content)

    # Hapus elemen kosong / whitespace di tepi
    scenes = [s.strip() for s in raw_scenes if s.strip()]

    # -------------------------------------------------
    # 2️⃣  Simpan ke DB
    # -------------------------------------------------
    user_id = update.effective_user.id
    await memory.init_user(user_id)  # buat dokumen bila belum ada

    # Reset story lama (agar tidak tercampur)
    await memory.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY",
                "selected_model": "gemini-2.5-flash",  # default, bisa di‑ubah lewat /model
                "story": [],                           # kosongkan dulu
                "genre": "imported",
                "prompt_template": "",                 # tidak dipakai lagi
            }
        },
    )

    # Simpan tiap scene sebagai satu entri dalam array `story`
    # Format story yang dipakai di `chat_engine` adalah list of dict:
    #   {"turn": int, "user": str, "ai": str}
    turn = 0
    for scene in scenes:
        # Detect apakah scene berisi USER atau AI, atau keduanya.
        # Pada file replay, formatnya:
        #   USER: <teks>
        #   AI:   <teks>
        user_match = re.search(r"USER:\s*(.+?)(?=\nAI:|$)", scene, flags=re.S)
        ai_match = re.search(r"AI:\s*(.+)", scene, flags=re.S)

        user_text = user_match.group(1).strip() if user_match else "(imported story)"
        ai_text = ai_match.group(1).strip() if ai_match else ""

        # Simpan ke koleksi story
        await memory.users.update_one(
            {"_id": user_id},
            {
                "$push": {
                    "story": {
                        "turn": turn,
                        "user": user_text,
                        "ai": ai_text,
                    }
                }
            },
        )
        turn += 1

    # -------------------------------------------------
    # 3️⃣  Tampilkan scene terakhir sebagai konfirmasi
    # -------------------------------------------------
    last_scene = await memory.get_last_scene(user_id)  # fungsi di memory.py
    if not last_scene:
        await update.message.reply_text("⚠️ Tidak ada scene yang dapat ditampilkan.")
        return

    await update.message.reply_text(
        "✅ *Story berhasil di‑import!* Berikut scene terakhir yang akan "
        "menjadi titik awal percakapan:\n\n"
        f"*TURN {last_scene['turn']}*\n"
        f"*USER:* {last_scene['user']}\n"
        f"*AI:* {last_scene['ai']}",
        parse_mode="Markdown",
    )


# ----------------------------------------------------------------------
# CHAT ENGINE (AI response)
# ----------------------------------------------------------------------
async def chat_engine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Proses percakapan utama – hanya bila user dalam state STORY."""
    user_id = update.effective_user.id
    user_msg = update.message.text

    data = await memory.get_user(user_id)

    # Tidak dalam state STORY → abaikan (biasanya user belum /start)
    if not data or data.get("state") != "STORY":
        return

    story = data["story"]

    # Buat prompt lengkap (history + user_msg)
    prompt = build_prompt(story, user_msg)

    # Simpan prompt untuk /retry_last
    await memory.save_last_prompt(user_id, prompt)

    try:
        selected_model = data.get("selected_model", "gemini-2.5-flash")
        logger.info("🔎 Menggunakan model: %s", selected_model)

        ai_text, model_used = await generate(prompt, selected_model)

        # Jika generate mengembalikan fallback (semua model error)
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
            [InlineKeyboardButton("🔁 Regenerate", callback_data="regen")],
            [InlineKeyboardButton("📖 Replay Story", callback_data="replay")],
        ]

        safe_text = ai_text[:3500]  # limit Telegram
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
            "⚠️ Terjadi error ketika memanggil AI.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# ----------------------------------------------------------------------
# REGENERATE
# ----------------------------------------------------------------------
async def regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan pilihan model untuk regenerate scene terakhir."""
    query = update.callback_query
    await query.answer()

    last_scene = await memory.get_last_scene(query.from_user.id)
    if not last_scene:
        await query.message.reply_text("❌ Tidak ada scene terakhir.")
        return

    # Simpan scene untuk proses rewrite selanjutnya
    context.user_data["regen_scene"] = last_scene

    # Pilih model (sama seperti menu /model)
    keyboard = []
    for label, model_name in AVAILABLE_MODELS.items():
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"regenmodel_{model_name}")]
        )

    await query.message.reply_text(
        "📌 Pilih model untuk regenerate:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_regen_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simpan model yang dipilih untuk proses regenerate."""
    query = update.callback_query
    await query.answer()

    model_name = query.data.replace("regenmodel_", "")
    context.user_data["regen_model"] = model_name

    await query.message.reply_text(
        "✍️ Kirim revisi/perbaikan cerita (contoh: \"jangan pindah lokasi\")."
    )


async def rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gunakan revisi + model terpilih untuk menghasilkan scene baru."""
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

    await update.message.reply_text(
        f"🔄 Regenerate pakai `{model_name}`...", parse_mode="Markdown"
    )

    ai_text, model_used = await generate(prompt, model_name)

    # Bersihkan state regen
    context.user_data.pop("regen_scene", None)
    context.user_data.pop("regen_model", None)

    keyboard = [
        [InlineKeyboardButton("🔁 Regenerate Lagi", callback_data="regen")]
    ]

    await update.message.reply_text(
        f"{ai_text[:3500]}\n\n🤖 {model_used}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ----------------------------------------------------------------------
# RETRY LAST PROMPT
# ----------------------------------------------------------------------
async def retry_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ulangi proses terakhir (biasanya dipanggil ketika fallback)."""
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


# ----------------------------------------------------------------------
# STATUS (opsional) – menampilkan ringkasan story saat ini
# ----------------------------------------------------------------------
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan jumlah scene dan scene terakhir yang tersimpan."""
    user_id = update.effective_user.id
    archive = await memory.get_full_story(user_id)

    if not archive:
        await update.message.reply_text("📂 Belum ada story untuk Anda.")
        return

    last = archive[-1]
    await update.message.reply_text(
        f"📊 *Story saat ini*\n"
        f"- Total scene: `{len(archive)}`\n"
        f"- Scene terakhir (TURN {last['turn']}):\n"
        f"  *USER*: {last['user'][:200]}\n"
        f"  *AI*: {last['ai'][:200]}",
        parse_mode="Markdown",
    )


# ----------------------------------------------------------------------
# MESSAGE ROUTER
# ----------------------------------------------------------------------
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Jika user berada dalam mode *regen* (telah pilih /regen),
    pertama panggil `rewrite`; bila tidak, jalankan `chat_engine`.
    """
    if "regen_scene" in context.user_data:
        await rewrite(update, context)
    else:
        await chat_engine(update, context)


# ----------------------------------------------------------------------
# ERROR HANDLER
# ----------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log semua exception yang tidak tertangani."""
    logger.error("Exception while handling update:", exc_info=context.error)


# ----------------------------------------------------------------------
# SET BOT COMMANDS (menu di Telegram)
# ----------------------------------------------------------------------
async def set_bot_commands(app: Application) -> None:
    commands = [
        BotCommand("start", "🏠 Menu Utama"),
        BotCommand("model", "🤖 Pilih Model AI"),
        BotCommand("replay", "📖 Replay Story (file txt)"),
        BotCommand("regen", "🔁 Regenerate Scene"),
        BotCommand("import", "📂 Open story from txt"),
        BotCommand("status", "ℹ️ Tampilkan status cerita"),
    ]
    await app.bot.set_my_commands(commands)


# ----------------------------------------------------------------------
# MAIN – inisialisasi aplikasi
# ----------------------------------------------------------------------
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
    app.add_handler(CommandHandler("status", status))

    # ---------- CALLBACK HANDLERS ----------
    app.add_handler(CallbackQueryHandler(select_genre, pattern="^genre_"))
    app.add_handler(CallbackQueryHandler(select_model, pattern="^model_"))
    app.add_handler(CallbackQueryHandler(regenerate, pattern="^regen$"))
    app.add_handler(CallbackQueryHandler(select_regen_model, pattern="^regenmodel_"))
    app.add_handler(CallbackQueryHandler(replay, pattern="^replay$"))
    app.add_handler(CallbackQueryHandler(retry_last, pattern="^retry_last$"))

    # ---------- MESSAGE HANDLERS ----------
    # 1️⃣ Teks biasa – chat utama
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_router)
    )
    # 2️⃣ Dokumen .txt – import story
    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("txt") & ~filters.COMMAND, handle_story_file
        )
    )

    # ---------- ERROR ----------
    app.add_error_handler(error_handler)

    # ---------- POST‑INIT ----------
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
