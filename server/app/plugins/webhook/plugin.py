"""Sends ZiraHive events to a web address as signed JSON."""
import hashlib
import hmac
import json


def wanted(event_name: str, setting: str | None) -> bool:
    names = {e.strip() for e in (setting or "*").split(",") if e.strip()}
    return "*" in names or event_name in names or event_name == "plugin.test"


async def on_event(event, ctx):
    url = (ctx.settings.get("url") or "").strip()
    if not url:
        raise ValueError("Set the address to send to first")
    if not wanted(event.name, ctx.settings.get("events")):
        return
    body = json.dumps({"event": event.name, "time": event.time, "data": event.data}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "X-ZiraHive-Event": event.name}
    secret = ctx.settings.get("secret") or ""
    if secret:
        headers["X-ZiraHive-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    async with ctx.http() as client:
        r = await client.post(url, content=body, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"{url} answered {r.status_code}")
