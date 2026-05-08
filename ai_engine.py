import asyncio
from google import genai
from config import GEMINI_API_KEY, MODELS

client = genai.Client(api_key=GEMINI_API_KEY)


async def generate(prompt):

    prompt = prompt[:12000]

    for _ in range(3):
        for model in MODELS:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt
                )

                if response and response.text:
                    return response.text.strip(), model

            except Exception as e:
                print("AI ERROR:", model, e)

        await asyncio.sleep(2)

    return "AI gagal merespon.", "none"
