import asyncio
from google import genai
from config import GEMINI_API_KEY, MODELS

client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# SAFE GENERATE (ANTI TIMEOUT + ANTI EMPTY + RETRY)
# =========================================================

async def generate(prompt):

    # 🔒 safety limit (biar gak kebablasan token)
    prompt = prompt[:12000]

    last_error = None

    for attempt in range(3):  # retry total 3 kali cycle

        for model in MODELS:

            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt
                )

                # =========================
                # VALIDASI RESPONSE
                # =========================
                if not response:
                    continue

                if not hasattr(response, "text"):
                    continue

                text = response.text

                if not text or len(text.strip()) < 5:
                    continue

                return text.strip(), model

            except Exception as e:
                last_error = str(e)
                print(f"[AI ERROR] {model}: {e}")

        # kalau semua model gagal 1 cycle → delay
        await asyncio.sleep(2)

    # fallback terakhir
    return (
        "AI gagal menghasilkan respon yang valid. Coba ulangi.",
        "fallback"
    )
