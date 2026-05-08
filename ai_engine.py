import asyncio
from google import genai
from config import GEMINI_API_KEY, MODELS

client = genai.Client(api_key=GEMINI_API_KEY)


async def generate(prompt):

    prompt = prompt[:12000]

    for _ in range(3):
        for model in MODELS:
            try:
                res = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt
                )

                if res and res.text:
                    return res.text.strip(), model

            except Exception as e:
                print("AI ERROR:", e)

    return "AI gagal", "none"
