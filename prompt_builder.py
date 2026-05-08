def build_prompt(story, user_msg):

    return f"""
KAMU ADALAH STORY ENGINE.

ATURAN:
- Jangan meta
- Jangan tahu masa depan
- Hormati jarak fisik scene
- Jangan bikin dialog tanpa akses ruang
- Kalau jauh → hanya teriakan / gesture
= 80 % berisi dialog dari narasinya

GENRE:
{story['genre']}

SUMMARY:
{story['summary']}

USER:
{user_msg}

OUTPUT FORMAT:
[LOCATION]
[SCENE]
[CHARACTER ACTION]
[DIALOG]
[NEXT HOOK]
"""
