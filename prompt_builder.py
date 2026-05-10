# --------------------------------------------------------------
# prompt_builder.py
# --------------------------------------------------------------
def build_prompt(metadata: dict, story: list, user_msg: str) -> str:
    """
    Parameters
    ----------
    metadata : dict
        {
            "genre": "...",
            "system_prompt": "...",
        }
    story    : list of scene dicts (ordered)
    user_msg : string – pesan terbaru user

    Returns
    -------
    str – prompt yang siap dikirim ke model Gemini / Gemma.
    """

    # 1️⃣  Ambil beberapa scene terakhir (maks 4) untuk konteks
    recent = story[-4:] if len(story) >= 4 else story
    context = ""
    for scene in recent:
        context += (
            f"TURN {scene['turn']}\n"
            f"USER: {scene['user']}\n"
            f"AI:   {scene['ai']}\n\n"
        )

    # 2️⃣  Sistem / aturan utama
    system_prompt = metadata.get("system_prompt", "")
    genre = metadata.get("genre", "")

    # 3️⃣  Susun prompt akhir
    prompt = f"""SYSTEM:
{system_prompt}
GENRE: {genre}
--- CONTEXT (last {len(recent)} turns) ---
{context}
--- USER INPUT ---
{user_msg}
"""
    return prompt
