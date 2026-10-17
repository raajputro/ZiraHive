# Plugins

Plugins are small Python add-ons that react to what happens in ZiraHive (new movies, uploads,
backups, watch parties) or add their own pages to the API. Turn them on and set them up in
**Settings > Server > Plugins**.

## Built in

| Plugin | What it does |
|---|---|
| **Webhook** | Sends each event as signed JSON to a web address: Home Assistant, n8n, Node-RED, your own script |
| **Telegram messages** | A Telegram message when new movies arrive, a backup fails, or a watch party starts |

### Telegram in two minutes

1. In Telegram, talk to **@BotFather**, send `/newbot`, and copy the token it gives you.
2. Send your new bot any message (bots can only write to people who wrote to them first).
3. Get your chat ID from **@userinfobot**. For a family group, add the bot to the group and use
   the group's ID.
4. In **Settings > Server > Plugins > Telegram messages**, fill in both, tick what you want to hear
   about, save, turn it on, and press **Send a test**.

### Webhook

Every request is a `POST` with a JSON body:

```json
{"event": "media.added", "time": "2026-10-17T20:15:03+00:00",
 "data": {"library": "Hindi Movies", "library_id": "…", "kind": "movies", "count": 2, "titles": ["3 Idiots", "Lagaan"]}}
```

and these headers:

| Header | Value |
|---|---|
| `X-ZiraHive-Event` | the event name |
| `X-ZiraHive-Signature` | `sha256=` + HMAC-SHA256 of the raw body with your signing secret |

Check the signature before trusting the request. In Python:

```python
import hashlib, hmac
expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
ok = hmac.compare_digest(expected, request.headers["X-ZiraHive-Signature"])
```

## Events

| Event | When | `data` |
|---|---|---|
| `file.uploaded` | a file or photo finished uploading | `owner`, `folder`, `filename`, `size`, `kind`, `mime`, `new_version`, `asset_id` |
| `media.added` | a scan found new movies or episodes | `library`, `library_id`, `kind`, `count`, `titles` (up to 50) |
| `backup.finished` | an offsite backup run ended | `status` (`ok` or `failed`), `message`, `snapshot`, `bytes_added` |
| `party.created` | a watch party was started or planned | `host`, `title`, `party_id`, `scheduled_at` |
| `user.created` | an admin added a person | `username`, `by`, `is_admin` |
| `plugin.test` | the **Send a test** button | `by`, `message` |

Events never contain passwords or file contents.

## Writing your own

A plugin is a folder in `plugins` inside ZiraHive's data folder (`ZIRAHIVE_DATA_PATH`, for example
`D:\ZiraHiveData\plugins\new-movie-sms`), with two files.

**plugin.json** says what it is:

```json
{
  "id": "new-movie-sms",
  "name": "New movie SMS",
  "description": "Texts me when new movies arrive.",
  "version": "1.0",
  "author": "Mahbub",
  "events": ["media.added"],
  "settings": [
    {"key": "phone", "label": "Phone number", "type": "text"},
    {"key": "api_key", "label": "SMS gateway key", "type": "secret"},
    {"key": "only_movies", "label": "Movies only, not episodes", "type": "bool", "default": true}
  ]
}
```

- `id`: lower-case letters, digits and dashes, the same as the folder name.
- `events`: the events it wants, or `["*"]` for all.
- Setting types: `text`, `secret` (never shown again once saved), `bool`, `number`, and `choice`
  (with `"choices": ["a", "b"]`).

**plugin.py** is the code. Both functions are optional:

```python
async def on_event(event, ctx):
    """event.name, event.data, event.time. Raise an exception to report a problem."""
    if ctx.settings["only_movies"] and event.data["kind"] != "movies":
        return
    async with ctx.http() as client:      # an httpx.AsyncClient
        await client.post("https://sms.example/api", json={
            "to": ctx.settings["phone"], "key": ctx.settings["api_key"],
            "text": f"{event.data['count']} new in {event.data['library']}"})


async def handle(request, ctx):
    """Answers /api/plugins/new-movie-sms/<anything> for signed-in people.
    ctx.user is who is asking, ctx.path the <anything> part. Return a dict (sent as JSON)
    or any FastAPI/Starlette Response."""
    if not ctx.user.is_admin:
        return {"error": "admins only"}
    return {"phone": ctx.settings["phone"], "path": ctx.path}
```

`ctx` also has `ctx.log` (a logger; messages go to `docker compose logs api`),
`ctx.notify_admins(title, body)` for a ZiraHive notification, `ctx.plugin_id` and `ctx.public_url`.

Then open **Settings > Server > Plugins**: the plugin appears (reload the page), fill in its
settings, turn it on and press **Send a test**.

### Good to know

- **A plugin runs with ZiraHive's own rights**, so only add code you trust. Nothing in a plugin
  folder runs until an admin turns it on, and ZiraHive asks again for plugins that aren't built in.
- **Plugins can't break ZiraHive.** Events are handed over in the background; a plugin that fails,
  or takes more than 15 seconds, is stopped and its error is shown on its card in Settings.
- **Changes to `plugin.py` load by themselves** on the next event. After changing `plugin.json`,
  reload the Settings page.
- A plugin of yours can't use the id of a built-in one.
- Need a Python package the Docker image doesn't have? Most things can be done with `httpx`, which
  is already there. Otherwise add the package to `server/requirements.txt` and rebuild.
