# Live TV (IPTV)

ZiraHive plays IPTV subscriptions that use the **Xtream Codes** API, the kind apps like Televizo and
IPTV Smarters Pro sign in to with a **server address, port, username and password**.

## Add your subscription

1. Open **Live TV** in the menu.
2. Fill in what your provider sent you:
   - **Server address**: for example `http://line.example.com` (with or without `http://`; a full
     `http://line.example.com:8080/player_api.php` link works too)
   - **Port**: for example `8080` (leave empty if it's already in the address)
   - **Username** and **Password**
3. Press **Add and start watching**. ZiraHive checks the login with your provider first.

An admin can tick **Let everyone in the family watch it**: the others then see it in Live TV, but
never the server address or login. Kids' profiles (an age limit set) don't get Live TV at all,
because IPTV channels carry no age ratings.

**Live TV > ⚙** (IPTV sources) shows each subscription's status, expiry date and how many screens it
allows, and lets you edit or remove it.

## Watching

- **Live TV**: categories on the left, channels in the middle, the player and programme guide
  (now and next) on the right. On a phone the player stays at the top while you scroll channels.
  Arrow up / down (or Page up / down, or channel up / down on a TV remote) changes channel.
  Double-click the picture for full screen.
- **Movies** and **Series**: browse by category, search, sort by newest, A to Z or rating. Films
  and episodes remember where you stopped.
- **Favourites**: the star on any channel, movie or series. Favourites are per person.

### Sound but no picture?

Some channels send video in a format browsers can't play (HEVC or MPEG-2). ZiraHive notices and
converts the picture automatically; you can also press the **convert** button (the circular arrows)
next to the channel name. It's remembered for that channel. Converting uses the PC's CPU (or the
NVIDIA GPU when `ZIRAHIVE_HW_ACCEL` allows it), so leave it off for channels that play fine.

## How it works

Everything goes through the ZiraHive server; the browser never talks to the provider:

- The provider's password is part of every stream address, so it stays on the server. It's stored in
  ZiraHive's database (inside your data folder) and is never sent to the web app.
- The web app only loads pictures and video from ZiraHive itself, and most providers only speak
  plain `http`, which an `https` page (your Tailscale address) couldn't load anyway. Channel logos
  and posters are fetched once and kept in the cache folder.
- **Live channels:** ffmpeg reads the provider's stream once and turns it into HLS. The picture is
  copied as it is (no CPU cost); the sound becomes AAC, because many channels send AC-3 or MP2 that
  browsers can't play. Everyone watching the same channel shares one connection to the provider.
- **Changing channel frees the old one straight away**, and closing the player tells the server to
  stop. Most plans allow only 1-2 screens at once, so a channel left running in the background would
  otherwise block the next one.
- **Movies and episodes:** MP4 and WebM files are passed through as they are (seeking works).
  MKV, AVI and others are converted on the fly with the same engine as your own films, with a full
  seek bar and a quality menu.

## When something doesn't play

| Message | What to do |
|---|---|
| *The IPTV server refused the username or password.* | Check the login; providers also refuse expired subscriptions. |
| *Can't reach the IPTV server.* | Check the address and port. Some providers block whole countries or need a VPN. |
| *The IPTV server refused this channel. Your plan may allow fewer screens at once.* | Something else is using your subscription (another app, another TV). Stop it, or wait a minute. |
| *This channel is off the air right now.* | The provider has nothing on that channel at the moment. |
| *Too many channels are playing at once.* | ZiraHive plays at most 8 IPTV streams at a time. |

Catch-up (replay of past programmes) and M3U playlist links aren't supported yet; Xtream Codes
logins are.
