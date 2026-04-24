import os
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG (TETAP) =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "User",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system"),
        "temp_char": s.get("temp_char")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI (TETAP) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-15:]) if history else "Start."
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            print(f"[AI] Model: {m}")
            return resp.text.strip(), m
        except:
            continue
    return None, None
#= ====== def build_system==========================
def build_system(tag, desc):
    return f"""
Kamu adalah RPG Engine dengan gaya penulisan Novel Visual yang ekspresif.

PERAN SAAT INI: {tag}
DESKRIPSI KARAKTER: {desc}

FORMAT OUTPUT WAJIB:
1. Dialog: Tulis langsung dengan tanda kutip "..." (Gunakan tanda seru jika emosional).
2. Aksi/Narasi: Tulis di dalam kurung dan cetak miring: *(Isi narasi deskriptif yang detail tentang gerakan, ekspresi, dan suasana)*.
3. Transisi Lokasi: Jika narasi berpindah tempat, awali dengan:
   ***
   **(Di [Nama Lokasi])**

ATURAN NARASI:
- Gunakan diksi yang dramatis (contoh: 'terbirit-birit', 'napas memburu', 'debuman keras').
- Fokus pada detail sensorik (suara bergema, rasa nyeri, tangan gemetar).
- Maksimal 2-4 paragraf.
- Jangan gunakan poin-poin.
"""

# ========= UI (OPSI SAVE DITAMBAHKAN) =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"),
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"),
         InlineKeyboardButton("📂 Load Slot", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="export_logs"),
         InlineKeyboardButton("↩️ Undo", callback_data="undo")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"),
         InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    text = text.replace("\n\n\n", "\n\n")
    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine\n\nMasukkan nama karakter utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"🔥 Selamat datang, {text}!", reply_markup=await menu_utama(uid))
        return

    # LOGIKA SAVE MANUAL
    if s["step"] == "save_name_input":
        save_data = {
            "user_id": uid,
            "save_name": text,
            "name": s["name"],
            "history": s["history"],
            "chars": s["chars"],
            "desc_utama": s["desc_utama"]
        }
        await archives.insert_one(save_data)
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Cerita berhasil disimpan ke slot: {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "import_chars":
        lines = text.split("\n")
        for line in lines:
            if ":" in line:
                c_name, c_desc = line.split(":", 1)
                s["chars"].append({"name": c_name.strip(), "desc": c_desc.strip()})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"✅ Karakter ditambahkan!", reply_markup=await menu_utama(uid))
        return

    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"desc_utama": text, "step": None})
        else:
            s["chars"][idx]["desc"] = text
            await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Update berhasil.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi {text}?")
        return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ NPC ditambahkan.", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        system = build_system(tag, desc)
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ AI sibuk.", reply_markup=await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "save_manual":
        if not s["history"]:
            await q.message.reply_text("⚠️ Belum ada cerita untuk disimpan.")
            return
        await save(uid, {"step": "save_name_input"})
        await q.message.reply_text("📝 Masukkan nama untuk slot simpanan ini:")

    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("_id", -1)
        items = await cursor.to_list(length=10)
        if not items:
            await q.message.reply_text("📂 Tidak ada arsip.")
            return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📂 Pilih Slot untuk Muat:", reply_markup=InlineKeyboardMarkup(kb))

  # GANTI BAGIAN LOAD LU DENGAN INI (Fix Nama Tokoh Utama)
    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            # Update state lokal dengan data dari database
            new_history = data.get("history", [])
            await save(uid, {
                "history": new_history, 
                "chars": data.get("chars", []), 
                "name": data.get("name", s["name"]),
                "desc_utama": data.get("desc_utama", s["desc_utama"]),
                "step": None # Reset step agar tidak nyangkut di input nama save
            })
            
            # Ambil 2 pesan terakhir untuk ditampilkan sebagai preview
            preview = "\n\n".join(new_history[-2:]) if new_history else "Riwayat kosong."
            
            await q.message.reply_text(
                f"✅ **Berhasil memuat slot:** {data['save_name']}\n\n"
                f"**Cuplikan Terakhir:**\n{preview}", 
                parse_mode="Markdown",
                reply_markup=await menu_utama(uid)
            )
    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": None, "name": None})
        await q.message.reply_text("🧹 Sesi dihapus total. Gunakan /start untuk baru.")

    # LOGIKA STANDAR (TIDAK BERUBAH)
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah", callback_data="add_new"), InlineKeyboardButton("📥 Import", callback_data="import_menu")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data == "import_menu":
        await save(uid, {"step": "import_chars"})
        await q.message.reply_text("Format:\nNama: Deskripsi")
    elif q.data == "export_logs":
        text = "\n\n".join(s["history"])
        file_data = io.BytesIO(text.encode()); file_data.name = "story.txt"
        await q.message.reply_document(file_data)
   elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        # Menentukan identitas karakter berdasarkan index
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        info = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        
        # Simpan index yang dipilih ke state agar sistem tahu siapa yang aktif
        await save(uid, {"selected": idx})
        
        # Susunan tombol sesuai gambar referensi
        kb = [
            [InlineKeyboardButton("🎮 Aksi (Lanjut)", callback_data=f"act_{idx}")],
            [InlineKeyboardButton("📖 New Story", callback_data=f"new_story_{idx}")],
            [InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"edit_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
        ]
        
        text_display = f"Karakter: {name}\n\nInfo: {info}"
        await q.edit_message_text(text_display, reply_markup=InlineKeyboardMarkup(kb))
elif q.data.startswith("new_story_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        
        # Membersihkan riwayat untuk memulai alur baru
        s["history"] = []
        system_prompt = build_system(name, desc)
        
        # Prompt otomatis mengambil dari deskripsi karakter
        starting_prompt = f"Buat adegan pembuka yang dramatis untuk {name} berdasarkan deskripsi ini: {desc}"
        
        await q.message.reply_text(f"🎬 Menyiapkan cerita baru untuk {name}...")
        
        # Generate konten pertama
        out, model_used = await generate(starting_prompt, system_prompt, s["history"])
        
        if out:
            s["history"].append(f"[{name}]: {out}")
            # Simpan semua status terbaru termasuk prompt terakhir untuk fitur Regen
            await save(uid, {
                "history": s["history"], 
                "selected": idx, 
                "last_prompt": starting_prompt, 
                "last_system": system_prompt,
                "step": None
            })
            await safe_send(q, out, name, await menu_utama(uid))
        else:
            await q.message.reply_text("⚠️ Gagal memulai cerita. Coba klik 🔄 Regen.", reply_markup=await menu_utama(uid))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"}); await q.message.reply_text(f"Aksi {name}?")
    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": f"updating_{idx}"}); await q.message.reply_text("Deskripsi?")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Kejadian?")
    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Undo.", reply_markup=await menu_utama(uid))
    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop()
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))
    elif q.data == "lanjut":
        out, _ = await generate("Lanjutkan cerita.", "Kamu narator RPG.", s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))
    elif q.data == "add_new": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")
    elif q.data == "main_menu": await q.edit_message_text("Menu:", reply_markup=await menu_utama(uid))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("🔥 RPG BOT WITH MANUAL SAVE SYSTEM READY")
    app.run_polling()
