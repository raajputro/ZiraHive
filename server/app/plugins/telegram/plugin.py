"""Short Telegram messages about what happens in ZiraHive."""


def message(event, s) -> str | None:
    d = event.data
    if event.name == "plugin.test":
        return "ZiraHive can send you messages here. 👋"
    if event.name == "media.added" and s.get("new_media"):
        titles = ", ".join(d.get("titles", [])[:5])
        more = d["count"] - min(5, len(d.get("titles", [])))
        return f"🎬 {d['count']} new in {d['library']}: {titles}" + (f" and {more} more" if more > 0 else "")
    if event.name == "backup.finished" and s.get("backups") and d.get("status") != "ok":
        return f"⚠️ Offsite backup failed: {d.get('message') or 'unknown error'}"
    if event.name == "party.created" and s.get("parties"):
        when = f" at {d['scheduled_at']}" if d.get("scheduled_at") else " now"
        return f"🍿 {d['host']} is watching {d['title']}{when}"
    if event.name == "user.created" and s.get("people"):
        return f"👤 {d['by']} added {d['username']} to ZiraHive"
    if event.name == "file.uploaded" and s.get("uploads"):
        return f"⬆️ {d['owner']} uploaded {d['filename']}"
    return None


async def on_event(event, ctx):
    s = ctx.settings
    text = message(event, s)
    if not text:
        return
    if not s.get("token") or not s.get("chat_id"):
        raise ValueError("Fill in the bot token and chat ID first")
    async with ctx.http() as client:
        r = await client.post(f"https://api.telegram.org/bot{s['token']}/sendMessage",
                              json={"chat_id": s["chat_id"], "text": text, "disable_web_page_preview": True})
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram said: {r.json().get('description', r.status_code)}")
