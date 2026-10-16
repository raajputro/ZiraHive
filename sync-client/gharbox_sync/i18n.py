"""The app's few words in English and Bangla (it follows the language of your GharBox account)."""
BN = {
    "GharBox Sync": "ঘরবক্স সিঙ্ক",
    "Sync now": "এখনই সিঙ্ক করুন",
    "Sync now, deletions included": "এখনই সিঙ্ক করুন, মোছাসহ",
    "Pause": "থামান",
    "Resume": "আবার চালু করুন",
    "Open the folder": "ফোল্ডার খুলুন",
    "Open GharBox": "ঘরবক্স খুলুন",
    "Quit": "বন্ধ করুন",
    "Up to date": "সব হালনাগাদ",
    "Syncing…": "সিঙ্ক হচ্ছে…",
    "Paused": "থেমে আছে",
    "Last synced {time}": "শেষ সিঙ্ক {time}",
    "Sign in again: {server}": "আবার সাইন ইন করুন: {server}",
    "Can't reach GharBox. Trying again soon.": "ঘরবক্সে পৌঁছানো যাচ্ছে না। একটু পরে আবার চেষ্টা হবে।",
    "{n} files synced": "{n}টি ফাইল সিঙ্ক হয়েছে",
    "Kept both copies of {name}: it changed on the PC and in GharBox.": "{name}-এর দুটো কপিই রাখা হয়েছে: পিসি আর ঘরবক্স দুই জায়গাতেই বদলেছিল।",
    "Set up GharBox Sync": "ঘরবক্স সিঙ্ক চালু করুন",
    "GharBox address": "ঘরবক্সের ঠিকানা",
    "Username": "ইউজারনেম",
    "Password": "পাসওয়ার্ড",
    "Code from your authenticator app": "অথেনটিকেটর অ্যাপের কোড",
    "Folder on this PC": "এই পিসির ফোল্ডার",
    "Choose…": "বাছুন…",
    "Folder in GharBox": "ঘরবক্সের ফোল্ডার",
    "Start with Windows": "উইন্ডোজের সাথে চালু হোক",
    "Start syncing": "সিঙ্ক শুরু করুন",
    "Signing in…": "সাইন ইন হচ্ছে…",
}

_lang = "en"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in ("en", "bn") else "en"


def t(text: str, **kw) -> str:
    s = BN.get(text, text) if _lang == "bn" else text
    return s.format(**kw) if kw else s
