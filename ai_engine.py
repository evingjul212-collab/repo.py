async def generate(prompt):

    prompt = prompt[:12000]

    for model in MODELS:

        try:
            print(f"TRY MODEL: {model}")

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=prompt
                ),
                timeout=25
            )

            if response and response.text:
                return response.text.strip(), model

        except asyncio.TimeoutError:
            print(f"{model} TIMEOUT")
            continue

        except Exception as e:
            print(f"{model} ERROR:", e)
            continue

    return (
        "AI sedang sibuk, coba lagi beberapa saat.",
        "fallback"
    )
