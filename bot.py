import os
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId 

# --- CONFIG ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# --- DATA INTEGRITY ---
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name", "User"),
        "desc_utama": s.get("desc_utama", "Tokoh Utama"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "temp_val": s.get("temp_val")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    return fix_state(s)

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)
    
async def tampilkan_blok_terbaru(uid, context, s):
    history = s.get("history", [])
    if history:
        # Ambil hanya 1 yang paling terakhir (hasil generate terbaru)
        teks = history[-1]
    else:
        teks = "📖 Belum ada cerita. Mulailah petualanganmu!"
    
    # Kirim pesan baru + Menu Utama
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))
#=================================
# --- ENGINE AI --- generator
async def generate_response(prompt, history, s, force_options=False):
    # s sekarang ada di posisi ketiga
    daftar_npc = "\n".join([f"- {c['name']}: {c['desc']}" for c in s.get("chars", [])])
    system = (
        f"Kamu adalah Penulis Novel Visual RomCom.\n"
        f"TOKOH UTAMA: {s['name']} ({s.get('desc_utama', '')})\n"
        f"DAFTAR NPC YANG TERSEDIA:\n{daftar_npc}\n\n"
        "TUGAS: Tulis cerita ±1000 karakter. Gunakan NPC yang relevan dari daftar di atas. "
        "Jika setting di rumah, gunakan NPC yang bekerja di rumah (seperti pembantu). "
        "GAYA: Dialog dominan, narasi suasana di awal. Bahasa gaul natural."
    )
    
    if force_options:
        system += "\nWAJIB akhiri dengan 4 pilihan aksi: A, B, C, D."
    
    context = "[RIWAYAT CERITA SEBELUMNYA]\n" + "\n".join(history[-3:]) if history else "Cerita baru dimulai."
    full_prompt = f"{system}\n\n{context}\n\n[INSTRUKSI SAAT INI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except: continue
    return None
# --- MENU UTAMA ---
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")], 
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), 
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")], 
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"), 
         InlineKeyboardButton("📂 Load Slot", callback_data="load_list")], 
        [InlineKeyboardButton("📖 Riwayat", callback_data="show_history"), 
         InlineKeyboardButton("↩️ Back", callback_data="undo")], 
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), 
         InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")] 
    ]
    return InlineKeyboardMarkup(kb)

# --- FUNGSI TAMPILKAN 2 BLOK ---
async def tampilkan_dua_blok(uid, context, s):
    history = s.get("history", [])
    if len(history) >= 2:
        teks = f"{history[-2]}\n\n{'-'*20}\n\n{history[-1]}"
    elif len(history) == 1:
        teks = history[-1]
    else:
        teks = "📖 Belum ada cerita. Mulailah petualanganmu!"
    
    await context.bot.send_message(chat_id=uid, text=teks, reply_markup=await menu_utama(uid))

# --- HANDLER PESAN TEKS ---
async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Halo {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_val": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Sekarang masukkan DESKRIPSI baru:"); return
    
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_val"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_val"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text("✨ Karakter diperbarui!", reply_markup=await menu_utama(uid)); return

    if s["step"] == "save_manual_step":
        # Ambil semua data penting agar saat di-load kembali ke kondisi semula
        save_data = {
            "user_id": uid,
            "save_name": text,
            "history": s["history"],
            "chars": s["chars"],
            "name": s["name"],
            "desc_utama": s.get("desc_utama", "Tokoh Utama") # Tambahkan ini agar deskripsi tidak hilang
        }
        # WAJIB pakai await agar data benar-benar masuk sebelum diproses lanjut
        await archives.insert_one(save_data)
        
        # Reset step agar bot kembali ke mode normal
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Slot '{text}' berhasil disimpan!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "action":
        if s["step"] == "action":
        # TAMBAHKAN 's' sebelum 'False'
        out = await generate_response(f"Aksi {tag}: {text}", s["history"], s, False)
        if out:
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"--- {tag} ---\n\n{out}", reply_markup=await menu_utama(uid)); return

    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], True)
        if out:
            s["history"].append(f"[STORY]: {out}"); await save(uid, {"history": s["history"]})
            await tampilkan_dua_blok(uid, context, s); return

# --- HANDLER TOMBOL ---
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "lanjut": # PERBAIKAN: Gunakan 'if' bukan 'elif' di awal
        loading_msg = await q.message.reply_text("⏳ Menyusun dialog intens (±1000 karakter)...")
        prompt_lanjut = "Lanjutkan alur cerita dengan dialog emosional dominan, sekitar 1000 karakter."
        out = await generate_response(prompt_lanjut, s["history"], s, True) 
        if out:
            await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            s["history"].append(f"[STORY]:\n{out}"); 
            await save(uid, {"history": s["history"]})
            await tampilkan_blok_terbaru(uid, context, s)
    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): 
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.message.reply_text("📋 **Daftar Karakter:**", reply_markup=InlineKeyboardMarkup(kb))
   #================================================
    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"selected": idx})
        # Ambil data Nama dan Deskripsi sesuai pilihan index
        if idx == -1:
            name = s["name"]
            desc = s.get("desc_utama", "Belum ada deskripsi untuk Tokoh Utama.")
        else:
            name = s["chars"][idx]["name"]
            desc = s["chars"][idx].get("desc", "Belum ada deskripsi untuk NPC ini.")
       # Buat tombol navigasi
        kb = [
            [InlineKeyboardButton("🎮 Aksi", callback_data="act_run")],
            [InlineKeyboardButton("🎬 New Story", callback_data="new_start")],
            [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
        ]
        
        # Tampilkan Nama dan Deskripsinya sekaligus
        teks_tampilan = (
            f"👤 **Detail Karakter**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📛 **Nama:** {name}\n"
            f"📖 **Deskripsi:**\n{desc}"
        )
        
        # Gunakan edit_message_text agar menu karakter tetap rapi di satu tempat
        await q.edit_message_text(teks_tampilan, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        #=================================
    elif q.data == "save_manual":
        # Kunci user ke step simpan agar pesan teks selanjutnya dianggap sebagai nama slot
        await save(uid, {"step": "save_manual_step"})
        await q.message.reply_text("💾 **Simpan Progress**\n\nKetik nama untuk Save Slot ini:")
    elif q.data.startswith("edit_"):
        idx = q.data.split("_")[1]; await save(uid, {"step": f"editname_{idx}"})
        await q.message.reply_text("Masukkan Nama Baru:")

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            s_new = {"history": data.get("history", []), "chars": data.get("chars", []), "name": data.get("name"), "step": None}
            await save(uid, s_new)
            await q.message.reply_text("✅ LOAD SUCCESS!")
            await tampilkan_dua_blok(uid, context, s_new)
    #=====================================================        
    # new story
    elif q.data == "new_start":
        idx = s.get("selected", -1)
        loading_msg = await q.message.reply_text("🎬 Menyiapkan skenario...")
        
        if idx == -1:
            # SKENARIO TOKOH UTAMA: Pilihkan satu NPC yang relevan
            prompt_awal = (
                f"Mulai cerita baru dari sudut pandang Tokoh Utama: {s['name']}. "
                f"Setting: Narasi suasana lokasi dan waktu yang detail. "
                f"INSTRUKSI KHUSUS: Pilih HANYA SATU NPC dari daftar yang paling relevan dengan deskripsi {s['name']} "
                f"(Misal: jika disebutkan tinggal dengan pembantu, panggil NPC pembantu). "
                f"NPC lain dilarang muncul. Fokus pada interaksi berdua saja."
            )
        else:
            # SKENARIO NPC: Hanya Tokoh Utama + NPC Pilihan
            npc_name = s["chars"][idx]["name"]
            npc_desc = s["chars"][idx].get("desc", "")
            prompt_awal = (
                f"Mulai cerita baru. Fokus interaksi antara {s['name']} (Tokoh Utama) dengan {npc_name} ({npc_desc}). "
                f"Setting: Narasi suasana lokasi dan waktu. "
                f"DILARANG memunculkan NPC lain selain {npc_name}. Fokus pada hubungan mereka berdua."
            )
        
        # Panggil AI (Pastikan urutan parameter: prompt, history, s, force_options)
        out = await generate_response(prompt_awal, [], s, True)
        
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            
            new_h = [f"[STORY]:\n{out}"]
            await save(uid, {"history": new_h})
            await tampilkan_blok_terbaru(uid, context, {"history": new_h})     
    #====================================================        
    elif q.data == "act_run": await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi:")
    elif q.data == "undo":
        if s["history"]:
            s["history"].pop() # Hapus satu baris riwayat
            await save(uid, {"history": s["history"]})
            await q.message.reply_text("↩️ Berhasil kembali ke alur sebelumnya.")
            await tampilkan_blok_terbaru(uid, context, s)
        else:
            await q.message.reply_text("📖 Riwayat sudah kosong.")
    elif q.data == "reset_confirm": await save(uid, {"step": "set_name", "history": [], "chars": []}); await q.message.reply_text("Reset! Namamu?")
    elif q.data == "main_menu": await q.message.reply_text("📱 **Menu Utama:**", reply_markup=await menu_utama(uid))
    elif q.data == "save_manual":
        await save(uid, {"step": "save_manual_step"})
        await q.message.reply_text("💾 **Simpan Progress**\n\nKetik nama untuk Save Slot ini:")
  #========================================================================================
    elif q.data == "regen":
        if not s["history"]:
            await q.message.reply_text("❌ Tidak ada cerita untuk di-regen!")
            return
        loading_msg = await q.message.reply_text("🔄 Menulis ulang cerita terakhir...")
        # 1. Hapus cerita terakhir yang dianggap jelek dari history
        s["history"].pop()
        
        # 2. Ambil prompt terakhir (AI akan baca konteks sisa history)
        # Kita minta AI lanjutin lagi seolah-olah yang jelek tadi gak pernah ada
        out = await generate_response("Ulangi bagian terakhir dengan alur yang lebih menarik, ±1000 karakter.", s["history"], True)
        
        if out:
            try: await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except: pass
            s["history"].append(f"[STORY]:\n{out}")
            await save(uid, {"history": s["history"]})
            await tampilkan_blok_terbaru(uid, context, s)
# --- START ---
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": []}) 
    await update.message.reply_text("Siapa namamu?")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    app.run_polling(drop_pending_updates=True)
