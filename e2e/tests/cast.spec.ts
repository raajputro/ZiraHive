import { expect, test } from "@playwright/test";

// A stand-in for Google's Cast library, so this runs without a Chromecast or the internet.
// It records what GharBox asks the "TV" to play.
const FAKE_SDK = `
(() => {
  const listeners = [];
  const player = { isConnected: false, isPaused: false, currentTime: 0, duration: 0 };
  const fire = () => listeners.forEach((f) => f());
  let session = null;
  window.chrome = { cast: {
    AutoJoinPolicy: { ORIGIN_SCOPED: "origin_scoped" },
    Image: function (url) { this.url = url; },
    media: {
      DEFAULT_MEDIA_RECEIVER_APP_ID: "CC1AD845",
      StreamType: { BUFFERED: "BUFFERED" }, TrackType: { TEXT: "TEXT" }, TextTrackType: { SUBTITLES: "SUBTITLES" },
      HlsSegmentFormat: { TS: "ts" }, HlsVideoSegmentFormat: { MPEG2_TS: "mpeg2_ts" },
      MediaInfo: function (id, type) { this.contentId = id; this.contentType = type; },
      GenericMediaMetadata: function () {},
      Track: function (id, type) { this.trackId = id; this.type = type; },
      LoadRequest: function (media) { this.media = media; },
    },
  } };
  window.cast = { framework: {
    RemotePlayerEventType: { ANY_CHANGE: "anyChanged" },
    RemotePlayer: function () { return player; },
    RemotePlayerController: function () {
      return {
        addEventListener: (_t, f) => listeners.push(f),
        removeEventListener: (_t, f) => listeners.splice(listeners.indexOf(f), 1),
        playOrPause: () => { player.isPaused = !player.isPaused; fire(); },
        seek: () => fire(),
      };
    },
    CastContext: { getInstance: () => ({
      setOptions: (o) => { window.__castOptions = o; },
      getCurrentSession: () => session,
      requestSession: async () => {
        session = {
          getCastDevice: () => ({ friendlyName: "Living room TV" }),
          loadMedia: async (req) => {
            window.__castLoaded = req;
            Object.assign(player, { isConnected: true, currentTime: req.currentTime || 0, duration: req.media.duration || 60 });
            setTimeout(fire, 0);
          },
        };
      },
      endCurrentSession: () => { session = null; player.isConnected = false; fire(); },
    }) },
  } };
  setTimeout(() => window.__onGCastApiAvailable && window.__onGCastApiAvailable(true), 0);
})();`;

test("casting a film to a Chromecast and controlling it from the page", async ({ page }) => {
  const media = await (await page.request.get("/api/media")).json();
  const film = media.find((m: { duration: number | null }) => m.duration);
  test.skip(!film, "Needs sample media (scripts/make-sample-media.sh)");
  const info = await page.request.get(`/api/media/${film.id}/cast`);
  test.skip(info.status() === 409, "Set GHARBOX_LAN_URL for the server under test");

  await page.route("https://www.gstatic.com/**", (r) => r.fulfill({ contentType: "text/javascript", body: FAKE_SDK }));
  await page.goto(`/play/${film.id}`);
  await page.getByRole("button", { name: "Cast to TV" }).click();

  const panel = page.getByRole("group", { name: "Playing on the TV" });
  await expect(panel.getByText("Playing on Living room TV")).toBeVisible();
  const loaded = await page.evaluate(() => (window as unknown as { __castLoaded: { media: { contentId: string; metadata: { title: string } } } }).__castLoaded);
  // the TV gets the home-network address and a link that only plays this film
  expect(loaded.media.contentId).toMatch(new RegExp(`/api/media/${film.id}/(stream|hls/.+/index\\.m3u8)\\?token=`));
  expect(loaded.media.metadata.title).toBeTruthy();
  const path = new URL(loaded.media.contentId).pathname + new URL(loaded.media.contentId).search;
  const anon = await page.context().browser()!.newContext({ baseURL: new URL(page.url()).origin, storageState: { cookies: [], origins: [] } });
  expect((await anon.request.get(path, { headers: { Range: "bytes=0-99" } })).ok()).toBeTruthy();
  const token = new URL(loaded.media.contentId).searchParams.get("token");
  expect((await anon.request.get(`/api/auth/me?token=${token}`)).status()).toBe(401);
  await anon.close();

  await panel.getByRole("button", { name: "Pause" }).click();
  await expect(panel.getByRole("button", { name: "Play" })).toBeVisible();
  await panel.getByRole("button", { name: "Stop casting" }).click();
  await expect(panel).toBeHidden();
  await expect(page.getByRole("button", { name: "Cast to TV" })).toBeVisible();
});
