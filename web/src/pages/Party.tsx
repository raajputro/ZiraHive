import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, SkipForward, Send, Users, Wifi, WifiOff, Play, Mic, MicOff, PhoneOff } from "lucide-react";
import { VoiceChat, voiceProblem, type PeerState, type VoicePeer } from "../voice";
import { api, ApiError, episodeCode, type Media, type Party, type Quality, type Tracks } from "../api";
import { useAuth } from "../App";
import { usePrefs } from "../prefs";
import { defaultAudio, defaultQuality, SubtitleTracks, TrackMenus, useSubtitle, useVideoSource } from "../video";

import { locale, t as tr } from "../i18n";
export default function PartyRoute() {
  const { id } = useParams();
  return id ? <PartyRoom key={id} id={id} /> : null;
}

interface RemoteState {
  media_id: string; playing: boolean; position: number; at: number; server_time: number;
  waiting_for: string[]; control: "host" | "everyone"; wait_for_all: boolean; by: string | null;
}
interface Person { user_id: string; username: string; devices: number; buffering: boolean; host: boolean; voice?: boolean }
type Line = { id: string; kind: "chat"; username: string; text: string } | { id: string; kind: "notice"; text: string };
interface Floating { id: number; emoji: string; username: string; left: number }

const REACTIONS = ["😂", "❤️", "👏", "😮", "😢", "🔥", "🎉", "👍"];
const when = new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function PartyRoom({ id }: { id: string }) {
  const { user } = useAuth();
  const { lowData } = usePrefs();
  const [party, setParty] = useState<Party | null>(null);
  const [media, setMedia] = useState<Media | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [audio, setAudio] = useState(0);
  const [subtitle, setSubtitle] = useState("off");
  const [remote, setRemote] = useState<RemoteState | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [lines, setLines] = useState<Line[]>([]);
  const [floating, setFloating] = useState<Floating[]>([]);
  const [conn, setConn] = useState<"connecting" | "live" | "reconnecting" | "ended" | "refused">("connecting");
  const [needsTap, setNeedsTap] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");

  const video = useRef<HTMLVideoElement>(null);
  const ws = useRef<WebSocket | null>(null);
  const remoteRef = useRef<RemoteState | null>(null);
  const offset = useRef(0);          // server clock minus ours, seconds
  const bestRtt = useRef(Infinity);
  const suppressUntil = useRef(0);   // ignore video events we caused ourselves
  const startAt = useRef<number | null>(null);
  const startTimer = useRef<number>();
  const waitTimer = useRef<number>();
  const sentBuffering = useRef(false);
  const lastReport = useRef(0);
  const chatEnd = useRef<HTMLDivElement>(null);
  // voice chat
  const voice = useRef<VoiceChat | null>(null);
  const myConn = useRef("");
  const iceServers = useRef<RTCIceServer[]>([]);
  const roster = useRef<VoicePeer[]>([]);
  const [inVoice, setInVoice] = useState(false);
  const [muted, setMuted] = useState(false);
  const [voicePeers, setVoicePeers] = useState<PeerState[]>([]);
  const [meSpeaking, setMeSpeaking] = useState(false);
  const [voiceMsg, setVoiceMsg] = useState("");
  const [voiceBusy, setVoiceBusy] = useState(false);
  const duck = useRef<{ base: number; quietSince: number } | null>(null);

  const serverNow = () => Date.now() / 1000 + offset.current;
  const expected = (s: RemoteState) => (s.playing ? s.position + Math.max(0, serverNow() - s.at) : s.position);
  const suppress = () => { suppressUntil.current = Date.now() + 700; };
  const suppressed = () => Date.now() < suppressUntil.current;
  const send = (msg: object) => { if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg)); };

  useEffect(() => { api.party(id).then(setParty).catch((e) => setError(e.message)); }, [id]);

  // ---------------------------------------------------- apply the room's state
  const apply = useCallback(() => {
    const v = video.current, s = remoteRef.current;
    if (!v || !s || !media || s.media_id !== media.id) return;
    const target = expected(s);
    window.clearTimeout(startTimer.current);
    suppress();
    if (v.readyState >= 1 && Math.abs(v.currentTime - target) > 0.5) v.currentTime = target;
    if (v.readyState < 1) startAt.current = target;
    if (!s.playing) { v.pause(); v.playbackRate = 1; return; }
    const wait = s.at - serverNow();
    const go = () => {
      suppress();
      v.currentTime = expected(s);
      v.play().then(() => setNeedsTap(false)).catch(() => setNeedsTap(true));
    };
    if (wait > 0) { v.pause(); startTimer.current = window.setTimeout(go, wait * 1000); } else go();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [media]);

  // -------------------------------------------------------- the live socket
  useEffect(() => {
    let closed = false, retry = 0, pinger = 0;
    const connect = () => {
      const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/parties/${id}/ws`);
      ws.current = sock;
      sock.onopen = () => {
        retry = 0;
        setConn("live");
        bestRtt.current = Infinity;
        for (let i = 0; i < 5; i++) setTimeout(() => send({ type: "ping", t0: Date.now() }), i * 150);
        pinger = window.setInterval(() => send({ type: "ping", t0: Date.now() }), 20_000);
      };
      sock.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        switch (msg.type) {
          case "hello":
            myConn.current = msg.conn;
            iceServers.current = msg.ice ?? [];
            setLines(msg.chat.map((c: { id: string; username: string; text: string }) => ({ ...c, kind: "chat" })));
            break;
          case "pong": {
            const rtt = Date.now() - msg.t0;
            if (rtt <= bestRtt.current) {  // the fastest round trip gives the best estimate
              bestRtt.current = rtt;
              offset.current = msg.server - (msg.t0 + rtt / 2) / 1000;
            }
            break;
          }
          case "state":
            remoteRef.current = msg;
            setRemote(msg);
            break;
          case "people": setPeople(msg.people); break;
          case "voice": roster.current = msg.peers; voice.current?.setRoster(msg.peers); break;
          case "signal": void voice.current?.signal(msg.from, msg.data); break;
          case "chat": setLines((l) => [...l.slice(-300), { ...msg, kind: "chat" }]); break;
          case "notice": setLines((l) => [...l.slice(-300), { id: `n${Date.now()}${Math.random()}`, kind: "notice", text: msg.text }]); break;
          case "react": {
            const f = { id: Date.now() + Math.random(), emoji: msg.emoji, username: msg.username, left: 10 + Math.random() * 75 };
            setFloating((x) => [...x.slice(-20), f]);
            setTimeout(() => setFloating((x) => x.filter((y) => y.id !== f.id)), 2600);
            break;
          }
          case "ended": closed = true; setConn("ended"); video.current?.pause(); break;
        }
      };
      sock.onclose = (e) => {
        window.clearInterval(pinger);
        if (voice.current) {  // the voice links were set up through this connection
          voice.current.leave();
          voice.current = null;
          setInVoice(false);
          setVoiceMsg(tr("Voice chat stopped when the connection dropped. Join again when it's back."));
        }
        if (closed) return;
        if (e.code >= 4400) { setConn("refused"); return; }
        setConn("reconnecting");
        retry = Math.min(retry + 1, 6);
        setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    return () => { closed = true; window.clearInterval(pinger); voice.current?.leave(); voice.current = null; ws.current?.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // --------------------------------------- load the title the room is playing
  useEffect(() => {
    if (!remote || remote.media_id === media?.id) return;
    Promise.all([api.mediaItem(remote.media_id), api.tracks(remote.media_id)]).then(([m, t]) => {
      startAt.current = remoteRef.current ? expected(remoteRef.current) : 0;
      setTracks(t);
      setAudio(defaultAudio(t));
      setQuality((q) => q && (q === "original" ? t.direct_play : t.qualities.includes(q as never)) ? q : defaultQuality(t, lowData));
      setMedia(m);
    }).catch((e) => setError(e instanceof ApiError ? e.message : tr("Couldn't load the video")));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote?.media_id]);

  useEffect(() => { apply(); }, [remote, apply]);
  useVideoSource(video, { media, tracks, quality, audio, startAt, autoplay: false, onError: setError });
  useSubtitle(video, subtitle, [media, quality, audio]);

  // ------------------------------------------- drift correction, every second
  useEffect(() => {
    const t = window.setInterval(() => {
      const v = video.current, s = remoteRef.current;
      if (!v || !s || !media || s.media_id !== media.id || v.readyState < 2) return;
      if (s.playing && serverNow() >= s.at && !sentBuffering.current) {
        const d = v.currentTime - expected(s);
        if (v.paused && !needsTap) { suppress(); void v.play().catch(() => setNeedsTap(true)); }
        if (Math.abs(d) > 1.5) { suppress(); v.currentTime = expected(s); v.playbackRate = 1; }
        else if (Math.abs(d) > 0.25) v.playbackRate = d > 0 ? 0.95 : 1.05;  // ease back, nobody notices
        else v.playbackRate = 1;
      }
      if (Date.now() - lastReport.current > 3000) { lastReport.current = Date.now(); send({ type: "report", position: v.currentTime }); }
    }, 1000);
    return () => window.clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [media, needsTap]);

  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "end" }); }, [lines]);

  // ---------------------------------------------------------- your actions
  const onPlay = () => { const v = video.current!; if (!suppressed()) send({ type: "play", position: v.currentTime }); };
  const onPause = () => { const v = video.current!; if (!suppressed() && !v.ended) send({ type: "pause", position: v.currentTime }); };
  const onSeeked = () => { const v = video.current!; if (!suppressed()) send({ type: "seek", position: v.currentTime }); };
  const onWaiting = () => {
    window.clearTimeout(waitTimer.current);
    waitTimer.current = window.setTimeout(() => {  // only count real stalls, not a quick hiccup
      if ((video.current?.readyState ?? 4) < 3 && !sentBuffering.current) { sentBuffering.current = true; send({ type: "buffering", state: true }); }
    }, 1500);
  };
  const onReady = () => {
    window.clearTimeout(waitTimer.current);
    if (sentBuffering.current) { sentBuffering.current = false; send({ type: "buffering", state: false }); }
  };
  const onEnded = () => { if (party?.is_host && media?.next_id) send({ type: "media", media_id: media.next_id }); };
  const tapToJoin = () => { setNeedsTap(false); apply(); };
  const joinVoice = async () => {
    setVoiceMsg("");
    const problem = voiceProblem();
    if (problem) {
      setVoiceMsg(problem === "insecure"
        ? tr("Voice chat needs a secure page: open ZiraHive at your https:// address, or http://localhost on the server PC.")
        : tr("This browser can't do voice chat. Try a recent Chrome, Edge, Firefox or Safari."));
      return;
    }
    setVoiceBusy(true);
    const v = new VoiceChat(send, myConn.current, iceServers.current);
    v.onChange = (peers, me) => {
      setVoicePeers((old) => (JSON.stringify(old) === JSON.stringify(peers) ? old : peers));
      setMeSpeaking(me);
      // lower the film while someone is talking, back up after a second of quiet
      const vid = video.current;
      if (!vid) return;
      const talking = peers.some((p) => p.speaking);
      if (talking && !duck.current) { duck.current = { base: vid.volume, quietSince: 0 }; vid.volume = vid.volume * 0.35; }
      else if (talking && duck.current) duck.current.quietSince = 0;
      else if (!talking && duck.current) {
        if (!duck.current.quietSince) duck.current.quietSince = Date.now();
        else if (Date.now() - duck.current.quietSince > 1000) { vid.volume = duck.current.base; duck.current = null; }
      }
    };
    try {
      await v.join();
      voice.current = v;
      v.setRoster(roster.current);
      setInVoice(true);
      setMuted(false);
    } catch (e) {
      setVoiceMsg(e instanceof DOMException && e.name === "NotAllowedError"
        ? tr("The microphone is blocked. Allow it for this site in the browser, then try again.")
        : tr("No microphone was found."));
    } finally { setVoiceBusy(false); }
  };
  const leaveVoice = () => {
    voice.current?.leave();
    voice.current = null;
    setInVoice(false);
    setVoicePeers([]);
    if (duck.current && video.current) { video.current.volume = duck.current.base; duck.current = null; }
  };
  const toggleMute = () => { const m = !muted; voice.current?.setMuted(m); setMuted(m); };
  const talking = new Set(voicePeers.filter((p) => p.speaking).map((p) => p.username));
  if (meSpeaking) talking.add(user.username);

  const sendChat = (e: FormEvent) => { e.preventDefault(); if (draft.trim()) { send({ type: "chat", text: draft }); setDraft(""); } };

  const answer = async (rsvp: "going" | "declined") => setParty(await api.rsvp(id, rsvp));
  const changeSettings = async (change: { control?: "host" | "everyone"; wait_for_all?: boolean }) => setParty(await api.updateParty(id, change));
  const end = async () => { if (confirm(tr("End the watch party for everyone?"))) setParty(await api.endParty(id)); };

  if (error && !party) return <div className="page cinema-page"><p className="error">{error}</p><Link to="/watch/parties">{tr("Watch parties")}</Link></div>;
  if (!party) return <div className="page cinema-page" aria-busy="true" />;
  if (conn === "ended" || party.ended_at) {
    return (
      <div className="page cinema-page">
        <h1>{party.title}</h1>
        <p className="muted">{tr("This watch party has ended.")}</p>
        <Link to="/watch/parties" className="button">{tr("Watch parties")}</Link>
      </div>
    );
  }
  if (conn === "refused") {
    return <div className="page cinema-page"><h1>{party.title}</h1><p className="error">{tr("You can't join this party. The title may not be available to your profile.")}</p></div>;
  }

  const hostOnly = remote?.control === "host" && !party.is_host;
  const future = party.scheduled_at && new Date(party.scheduled_at).getTime() > Date.now();

  return (
    <div className="party-page">
      <Link to="/watch/parties" className="back"><ArrowLeft size={18} />{" "}{tr("Watch parties")}</Link>
      <div className="party-layout">
        <section className="party-main">
          <header className="party-head">
            <h1>{party.title}</h1>
            <span className={`conn ${conn}`}>{conn === "live" ? <Wifi size={15} /> : <WifiOff size={15} />}
              {conn === "live" ? tr("{length} watching", { length: people.length }) : conn === "connecting" ? tr("Connecting") : tr("Reconnecting")}</span>
          </header>
          {future && (
            <div className="party-banner">{tr("Starts")}{" "}{when.format(new Date(party.scheduled_at!))}{tr(". You can come in early and chat.")}{party.my_rsvp && (
                <span className="rsvp">
                  <button className={party.my_rsvp === "going" ? "primary" : ""} onClick={() => void answer("going")}>{tr("Going")}</button>
                  <button className={party.my_rsvp === "declined" ? "primary" : ""} onClick={() => void answer("declined")}>{tr("Can't make it")}</button>
                </span>
              )}
            </div>
          )}
          <div className="player-frame">
            <video ref={video} controls playsInline preload="auto" onPlay={onPlay} onPause={onPause} onSeeked={onSeeked}
              onWaiting={onWaiting} onPlaying={onReady} onCanPlay={onReady} onEnded={onEnded}
              onLoadedMetadata={() => apply()}>
              {media && tracks && <SubtitleTracks media={media} tracks={tracks} />}
            </video>
            <div className="reactions-layer" aria-hidden>
              {floating.map((f) => <span key={f.id} className="float" style={{ left: `${f.left}%` }}>{f.emoji}<small>{f.username}</small></span>)}
            </div>
            {needsTap && (
              <button className="overlay-btn tap" onClick={tapToJoin}><Play size={18} fill="currentColor" />{" "}{tr("Tap to join the party")}</button>
            )}
            {remote && remote.waiting_for.length > 0 && (
              <div className="overlay-wait" role="status">{tr("Waiting for")}{" "}{remote.waiting_for.join(", ")}{" "}{tr("to load…")}</div>
            )}
          </div>
          <div className="player-controls">
            {tracks && quality && (
              <TrackMenus tracks={tracks} quality={quality} setQuality={setQuality} audio={audio} setAudio={setAudio}
                subtitle={subtitle} setSubtitle={setSubtitle} />
            )}
            {party.is_host && media?.next_id && (
              <button onClick={() => send({ type: "media", media_id: media.next_id })}><SkipForward size={16} />{" "}{tr("Next episode for everyone")}</button>
            )}
          </div>
          {media?.series_id && <p className="episode-code">{media.series_title}, {episodeCode(media)}</p>}
          {hostOnly && <p className="muted small">{party.host}{" "}{tr("controls playback in this party.")}</p>}
          {remote?.by && <p className="muted small">{tr("Last change by")}{" "}{remote.by}.</p>}
          {error && <p className="error" role="alert">{error}</p>}
        </section>

        <aside className="party-side">
          <section>
            <h2><Users size={16} aria-hidden />{" "}{tr("People")}</h2>
            <ul className="people">
              {people.map((p) => (
                <li key={p.user_id}>
                  <span className={`dot ${p.buffering ? "loading" : "on"}`} aria-hidden />
                  {p.username}{p.host && <span className="tag">{tr("host")}</span>}
                  {p.voice && <Mic size={14} className={`voice-mic ${talking.has(p.username) ? "talking" : ""}`}
                    aria-label={talking.has(p.username) ? tr("talking") : tr("in voice chat")} />}
                  {p.buffering && <span className="muted small">{" "}{tr("loading")}</span>}
                  {p.devices > 1 && <span className="muted small"> {p.devices}{" "}{tr("devices")}</span>}
                </li>
              ))}
              {party.members.filter((m) => !people.some((p) => p.user_id === m.user_id)).map((m) => (
                <li key={m.user_id} className="away">
                  <span className="dot" aria-hidden />{m.username}
                  <span className="muted small"> {m.rsvp === "going" ? "coming" : m.rsvp === "declined" ? tr("not coming") : "invited"}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="voice-panel" aria-label={tr("Voice chat")}>
            {inVoice ? (
              <>
                <p className="small">{voicePeers.length === 0 ? tr("You're in the voice chat. Waiting for others to join.")
                  : voicePeers.every((p) => p.connected) ? tr("Talking with {names}", { names: voicePeers.map((p) => p.username).join(", ") })
                  : tr("Connecting voice…")}</p>
                <div className="admin-row">
                  <button className={muted ? "" : "primary"} onClick={toggleMute} aria-pressed={muted}>
                    {muted ? <><MicOff size={16} />{" "}{tr("Unmute")}</> : <><Mic size={16} />{" "}{tr("Mute")}</>}</button>
                  <button onClick={leaveVoice}><PhoneOff size={16} />{" "}{tr("Leave voice")}</button>
                </div>
              </>
            ) : (
              <button onClick={() => void joinVoice()} disabled={voiceBusy || conn !== "live"}><Mic size={16} />{" "}{tr("Join voice chat")}</button>
            )}
            {voiceMsg && <p className="muted small" role="status">{voiceMsg}</p>}
          </section>

          <section className="chat">
            <h2>{tr("Chat")}</h2>
            <div className="chat-lines" aria-live="polite">
              {lines.length === 0 && <p className="muted small">{tr("Say hello. Messages stay with the party.")}</p>}
              {lines.map((l) => l.kind === "chat"
                ? <p key={l.id} className={l.username === user.username ? "mine" : ""}><strong>{l.username}</strong> {l.text}</p>
                : <p key={l.id} className="notice-line">{l.text}</p>)}
              <div ref={chatEnd} />
            </div>
            <div className="reaction-bar" role="group" aria-label={tr("Reactions")}>
              {REACTIONS.map((r) => <button key={r} className="icon" onClick={() => send({ type: "react", emoji: r })} aria-label={tr("React {r}", { r: r })}>{r}</button>)}
            </div>
            <form className="chat-form" onSubmit={sendChat}>
              <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={tr("Message")} maxLength={500} aria-label={tr("Chat message")} />
              <button className="icon" aria-label={tr("Send")}><Send size={17} /></button>
            </form>
          </section>

          {party.is_host && (
            <section className="host-tools">
              <h2>{tr("Host")}</h2>
              <label>{tr("Who can pause and skip")}<select value={party.control} onChange={(e) => void changeSettings({ control: e.target.value as "host" | "everyone" })}>
                  <option value="everyone">{tr("Everyone")}</option>
                  <option value="host">{tr("Only me")}</option>
                </select>
              </label>
              <label className="check"><input type="checkbox" checked={party.wait_for_all}
                onChange={(e) => void changeSettings({ wait_for_all: e.target.checked })} />{" "}{tr("Wait for anyone whose video is loading")}</label>
              <button className="danger" onClick={() => void end()}>{tr("End the party")}</button>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
