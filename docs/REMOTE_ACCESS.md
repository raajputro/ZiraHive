# Using GharBox away from home, safely

GharBox gets two addresses:

| Address | Who can open it | What it shows |
|---|---|---|
| `https://gharbox.<your-tailnet>.ts.net` | Only your and your family's devices, signed in to Tailscale | Everything: sign in, photos, files, watch, settings |
| `https://gharbox.<your-tailnet>.ts.net:8443` | Anyone on the internet | **Share links only** (`/s/...`). Nothing else exists there |

Why this design:

- **Nothing on your router is opened.** Tailscale makes an encrypted WireGuard connection from
  your phone to your PC. It also works behind CGNAT, which most Bangladeshi ISPs use and which
  makes normal port forwarding impossible.
- **Strangers can't even reach the sign-in page.** The private address only answers devices in
  your Tailscale network. The public address is a separate site that serves share links and
  returns "Not found" for everything else, including the sign-in page and the API. GharBox
  checks this a second time on the server, so one mistake doesn't open the rest.
- **HTTPS everywhere, with real certificates** issued for your `ts.net` name.

Tailscale's free Personal plan covers this: up to 6 people and unlimited devices.

## Set it up (about 15 minutes)

1. **Make a Tailscale account** at https://login.tailscale.com (sign in with Google, Microsoft
   or GitHub).

2. **Turn on HTTPS names.** In the admin console open **DNS**, make sure **MagicDNS** is on, then
   press **Enable HTTPS** under HTTPS Certificates.

3. **Allow the public share address (Funnel).** Open **Access controls** and add this inside the
   policy file, next to the existing sections, then save:

   ```json
   "nodeAttrs": [
     { "target": ["autogroup:member"], "attr": ["funnel"] }
   ],
   ```

   Skip this step if you don't want public share links (see below).

4. **Make an auth key.** Open **Settings > Keys > Generate auth key**. Leave "Reusable" and
   "Ephemeral" off, and copy the key (`tskey-auth-...`).

5. **Put it in `.env`** next to `docker-compose.yml`:

   ```
   TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx
   ```

6. **Start GharBox with remote access:**

   ```powershell
   docker compose --profile remote up -d --build
   docker compose logs tailscale
   ```

   In the admin console under **Machines** you'll now see `gharbox`, with its full name, for
   example `gharbox.tail1234.ts.net`. The key is only needed once; you can delete it from
   `.env` afterwards.

7. **Tell GharBox its public share address.** In `.env`:

   ```
   GHARBOX_PUBLIC_URL=https://gharbox.tail1234.ts.net:8443
   ```

   then `docker compose --profile remote up -d`. Share links you make now use this address.

8. **On each phone and laptop:** install the free Tailscale app, sign in with the same account,
   then open `https://gharbox.tail1234.ts.net`. On a phone, use **Add to Home Screen** (Safari:
   Share button; Chrome: menu) and GharBox opens like an app.

9. **Family:** in the Tailscale admin console, **Users > Invite users**. Each person installs
   Tailscale, accepts the invite, and gets their own GharBox account from you in
   **Settings > People**.

10. **Check the result:** in GharBox, **Settings > Server > Security check** should show no red
    items. Turn on two-factor sign-in for every admin (**Settings > Your account**).

## Options

- **No public share links at all:** set `TS_SERVE_FILE=serve-private-only.json` in `.env` and run
  `docker compose --profile remote up -d`. Links then work only for people on your Tailscale.
- **Only this PC on the home network:** set `GHARBOX_BIND=127.0.0.1`. Every other device, even at
  home, must then use Tailscale. Smart TVs without a Tailscale app won't reach GharBox.
- **Big movies to visitors:** public share traffic is relayed through Tailscale's servers and
  isn't meant for heavy streaming. Share photos and documents freely; for movies, invite the
  person to your Tailscale instead.

## What protects what

| Threat | Protection |
|---|---|
| Someone on the internet finds your server | The app isn't on the internet. Only share links are, through a separate site |
| Someone guesses a share link | Links are 22 random characters. Add a password and an expiry for anything private |
| Password guessing | 10 tries per account and 30 per address in 15 minutes, then a wait. Two-factor sign-in |
| Stolen phone | **Settings > Your account > Sign out everywhere**, and remove the device in Tailscale |
| Eavesdropping on café Wi-Fi | WireGuard encryption plus HTTPS. Cookies are marked Secure on HTTPS |
| A malicious website using your signed-in browser | SameSite cookies, strict Content-Security-Policy, no framing |
| Leaked sign-in links | Sign-in tokens aren't accepted in URLs, except the 24-hour video link for VLC |
| Someone reading your database or Redis | Neither is published outside Docker's private network |
| You don't notice an attack | The activity log records every sign-in, failure, share and admin change |

## Fully self-hosted alternatives

Tailscale's apps are open source, but its coordination service is not. If you want nothing from
a company at all:

- **Headscale** is an open-source Tailscale coordination server. It needs a small server with a
  public IP (some cloud providers have free tiers). The Tailscale apps then connect to it.
- **WireGuard** directly works if your ISP gives you a real public IP (no CGNAT): forward one
  UDP port to the PC. Ask your ISP whether you have a public IP; some offer one for a fee.

Avoid exposing the main GharBox site directly to the internet with port forwarding. The share-only
design above is safer.

## Troubleshooting

- **`gharbox` doesn't appear in Machines:** `docker compose logs tailscale`. An expired or used
  key shows an auth error: make a new one and restart.
- **Certificate errors on the private address:** HTTPS Certificates aren't enabled (step 2). The
  first visit can take a minute while the certificate is issued.
- **The public :8443 address doesn't open:** Funnel isn't allowed in the policy (step 3), or you
  used `serve-private-only.json`. `docker compose exec tailscale tailscale funnel status` shows
  what's published.
- **A share link opens the private address:** set `GHARBOX_PUBLIC_URL` (step 7) and make the link
  again.
