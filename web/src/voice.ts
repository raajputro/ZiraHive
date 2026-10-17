// Voice chat in a watch party: every device in the voice chat talks to every other one directly
// (WebRTC, encrypted), with GharBox only passing the set-up messages along the party socket.
// At home and over Tailscale devices reach each other directly; no outside server is used.

export interface VoicePeer { conn: string; username: string; muted: boolean }
export interface PeerState { conn: string; username: string; muted: boolean; speaking: boolean; connected: boolean }

type Send = (msg: object) => void;

const LOUD = 0.03;  // level that counts as talking (0 to 1)
const HOLD = 600;   // ms the talking light stays on after the last sound

interface Link { pc: RTCPeerConnection; audio: HTMLAudioElement; level?: () => number; pending: RTCIceCandidateInit[] }

/** Why voice can't work on this page, or null. */
export function voiceProblem(): "insecure" | "unsupported" | null {
  if (!window.isSecureContext) return "insecure";
  if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) return "unsupported";
  return null;
}

export class VoiceChat {
  private links = new Map<string, Link>();
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private myLevel: (() => number) | null = null;
  private roster: VoicePeer[] = [];
  private timer = 0;
  private ticks = 0;
  private loudAt = new Map<string, number>();  // when each device last made a sound ("me" = this one)
  muted = false;
  onChange: (peers: PeerState[], meSpeaking: boolean) => void = () => undefined;

  constructor(private send: Send, private me: string, private ice: RTCIceServer[]) {}

  get active() { return this.stream !== null; }

  async join(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.ctx = new AudioContext();
    void this.ctx.resume();
    this.myLevel = this.meter(this.stream);
    this.muted = false;
    this.send({ type: "voice", join: true, muted: false });
    this.timer = window.setInterval(() => this.sample(), 50);
    this.connectAll();
  }

  leave(): void {
    this.send({ type: "voice", join: false });
    for (const conn of [...this.links.keys()]) this.drop(conn);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close();
    this.ctx = null;
    window.clearInterval(this.timer);
    this.onChange([], false);
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.stream?.getAudioTracks().forEach((t) => { t.enabled = !muted; });
    this.send({ type: "voice", join: true, muted });
  }

  /** The party's voice roster changed (someone joined, left or muted). */
  setRoster(peers: VoicePeer[]): void {
    this.roster = peers;
    for (const conn of [...this.links.keys()]) if (!peers.some((p) => p.conn === conn)) this.drop(conn);
    this.connectAll();
    this.report();
  }

  /** A set-up message from another device. */
  async signal(from: string, data: { description?: RTCSessionDescriptionInit; candidate?: RTCIceCandidateInit }): Promise<void> {
    if (!this.stream) return;
    const link = this.links.get(from) ?? this.open(from);
    try {
      if (data.description) {
        await link.pc.setRemoteDescription(data.description);
        for (const c of link.pending.splice(0)) await link.pc.addIceCandidate(c).catch(() => undefined);
        if (data.description.type === "offer") {
          await link.pc.setLocalDescription(await link.pc.createAnswer());
          this.send({ type: "signal", to: from, data: { description: link.pc.localDescription } });
        }
      } else if (data.candidate) {
        if (link.pc.remoteDescription) await link.pc.addIceCandidate(data.candidate).catch(() => undefined);
        else link.pending.push(data.candidate);
      }
    } catch { /* a broken set-up: the next roster change tries again */ }
  }

  /** Everyone in the voice chat I'm not connected to yet. To avoid both sides calling at once,
   *  the device with the larger id makes the call and the other answers. */
  private connectAll(): void {
    if (!this.stream) return;
    for (const p of this.roster) {
      if (p.conn === this.me || this.links.has(p.conn) || this.me < p.conn) continue;
      const link = this.open(p.conn);
      void (async () => {
        await link.pc.setLocalDescription(await link.pc.createOffer());
        this.send({ type: "signal", to: p.conn, data: { description: link.pc.localDescription } });
      })();
    }
  }

  private open(conn: string): Link {
    const pc = new RTCPeerConnection({ iceServers: this.ice });
    const audio = new Audio();
    audio.autoplay = true;
    const link: Link = { pc, audio, pending: [] };
    this.links.set(conn, link);
    this.stream?.getTracks().forEach((t) => pc.addTrack(t, this.stream!));
    pc.onicecandidate = (e) => { if (e.candidate) this.send({ type: "signal", to: conn, data: { candidate: e.candidate.toJSON() } }); };
    pc.ontrack = (e) => {
      const remote = e.streams[0] ?? new MediaStream([e.track]);
      audio.srcObject = remote;
      void audio.play().catch(() => undefined);
      link.level = this.meter(remote);
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed") { this.drop(conn); this.connectAll(); }
      this.report();
    };
    return link;
  }

  private drop(conn: string): void {
    const link = this.links.get(conn);
    if (!link) return;
    link.pc.close();
    link.audio.srcObject = null;
    this.links.delete(conn);
  }

  /** A function returning how loud a stream is right now (0 to 1). */
  private meter(stream: MediaStream): () => number {
    if (!this.ctx) return () => 0;
    const src = this.ctx.createMediaStreamSource(stream);
    const an = this.ctx.createAnalyser();
    an.fftSize = 2048;
    src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    return () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += (v - 128) ** 2;
      return Math.sqrt(sum / buf.length) / 128;
    };
  }

  /** Listens often (speech has short gaps) and reports a few times a second. */
  private sample(): void {
    const t = Date.now();
    if ((this.myLevel?.() ?? 0) > LOUD) this.loudAt.set("me", t);
    for (const [conn, link] of this.links) if ((link.level?.() ?? 0) > LOUD) this.loudAt.set(conn, t);
    if (++this.ticks % 4 === 0) this.report();
  }

  private report(): void {
    if (!this.stream) return;
    const t = Date.now();
    const recent = (k: string) => t - (this.loudAt.get(k) ?? 0) < HOLD;
    const peers = this.roster.filter((p) => p.conn !== this.me).map((p) => ({
      ...p, connected: this.links.get(p.conn)?.pc.connectionState === "connected",
      speaking: !p.muted && recent(p.conn),
    }));
    this.onChange(peers, !this.muted && recent("me"));
  }
}
