def generate_romcom(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=f"""
Buat cerita ROMCOM lucu, ringan, banyak dialog.
Gaya Gen Z Indonesia, ending happy.

Ide: {prompt}

Format:
Judul:
Karakter:
Cerita:
"""
        )

        if hasattr(response, "text") and response.text:
            return response.text

        # fallback aman
        try:
            return response.candidates[0].content.parts[0].text
        except:
            return "⚠️ AI tidak merespon dengan benar, coba lagi."

    except Exception as e:
        return f"❌ Error AI: {str(e)}"
