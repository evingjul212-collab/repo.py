# Contoh alur pengambilan data untuk prompt
def start_prompt(update, context):
    # Tahap 1: Tanya Gender
    keyboard = [['Laki-laki', 'Perempuan', 'Non-binary']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    update.message.reply_text("Pilih Gender subyek:", reply_markup=reply_markup)
    return GENDER

def get_gender(update, context):
    context.user_data['gender'] = update.message.text
    # Tahap 2: Tanya Gaya Rambut
    update.message.reply_text("Ketik atau pilih gaya rambut (contoh: undercut, long wavy, bald):")
    return HAIR_STYLE

def get_hair(update, context):
    context.user_data['hair'] = update.message.text
    # Tahap 3: Tanya Latar Belakang
    update.message.reply_text("Ingin latar di mana? (contoh: di hutan, di kota masa depan):")
    return BACKGROUND

def generate_final_prompt(update, context):
    # Menggabungkan semua input menjadi satu prompt AI
    user = context.user_data
    final_prompt = (
        f"A high-quality photo of a {user['gender']} "
        f"with {user['hair']} hairstyle, "
        f"standing in {user['background']}, "
        f"8k resolution, cinematic lighting."
    )
    update.message.reply_text(f"✅ Prompt kamu sudah siap:\n\n`{final_prompt}`")
    return ConversationHandler.END
