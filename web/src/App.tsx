import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useStickyHeads } from "./stickyHead";
import { nativeApp } from "./native";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Images, Folder, Clapperboard, Tv, Headphones, BookOpen, MoonStar, Trash2, Settings, LogOut, Fingerprint, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { api, ApiError, type User } from "./api";
import { cancelled, getPasskey, passkeyProblem } from "./passkeys";
import { UploadProvider } from "./uploads";
import { PrefsProvider } from "./prefs";
import { AudioProvider } from "./audio";
import NowPlaying from "./components/NowPlaying";
import HiveMark from "./components/HiveMark";
import NotificationBell from "./components/Notifications";
import PhotosPage from "./pages/Photos";
import { CleanupPage, PeoplePage, PersonPage, PhotoSearchPage } from "./pages/SmartPhotos";
import AskPage from "./pages/Ask";
import AlbumsPage, { AlbumPage } from "./pages/Albums";
import PublicSharePage from "./pages/PublicShare";
import FilesPage from "./pages/Files";
import FileDuplicatesPage from "./pages/FileDuplicates";
import WatchHome, { LibraryPage } from "./pages/Watch";
import SeriesPage from "./pages/Series";
import PlayerRoute from "./pages/Player";
import { LinkLibraryPage, LinkPlayerPage, LinkSeriesPage } from "./pages/Linked";
import PartyRoute from "./pages/Party";
import PartiesPage from "./pages/Parties";
import TrashPage from "./pages/Trash";
import { AlbumDetailPage, AlbumsPage as MusicAlbumsPage, ArtistDetailPage, ArtistsPage, AudiobookPage, AudiobooksPage, ListenHome,
  PlaylistDetailPage, PlaylistsPage, SongsPage } from "./pages/Listen";
import { ReadHome, ReadLibraryPage, ReadSeriesPage } from "./pages/Read";
import { NamazPage, PrayerAlerts, QariPage, QuranHomePage, SurahPage, SurahsPage } from "./pages/Quran";
import ReaderRoute from "./pages/Reader";
import VaultPage from "./pages/Vault";
import PhotoVaultPage from "./pages/PhotoVault";
import ScanPage from "./pages/Scan";
import AdminPage from "./pages/Admin";
import { TvHome, TvMoviePage, TvPage, TvPlayerPage, TvSeriesPage, TvSourcesPage } from "./pages/Tv";

import { t as tr, adoptAccountLanguage, lang, setLang } from "./i18n";
const RAIL_KEY = "zirahive.nav.collapsed";
interface AuthCtx { user: User; signOut: () => void; refreshUser: () => void }
const AuthContext = createContext<AuthCtx | null>(null);
export const useAuth = () => useContext(AuthContext)!;

export default function App() {
  // Share links work without an account, so they bypass sign-in entirely.
  const share = location.pathname.match(/^\/s\/([A-Za-z0-9_-]+)/);
  if (share) return <PrefsProvider><PublicSharePage token={share[1]} /></PrefsProvider>;
  return <PrefsProvider><SignedInApp /></PrefsProvider>;
}

function SignedInApp() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    api.me().then((u) => { adoptAccountLanguage(u.language); setUser(u); }).catch(async () => {
      setNeedsSetup((await api.setupStatus().catch(() => ({ needs_setup: false }))).needs_setup);
      setUser(null);
    });
    const onSignedOut = () => setUser(null);
    window.addEventListener("zirahive:signed-out", onSignedOut);
    return () => window.removeEventListener("zirahive:signed-out", onSignedOut);
  }, []);

  if (user === undefined) return <div className="boot" aria-busy="true" />;
  if (user === null) return <SignIn firstRun={needsSetup} onSignedIn={(u) => { adoptAccountLanguage(u.language); setNeedsSetup(false); setUser(u); }} />;

  const signOut = () => { nativeApp?.signedOut(); void api.logout().finally(() => setUser(null)); };
  const refreshUser = () => { void api.me().then(setUser).catch(() => undefined); };
  return (
    <AuthContext.Provider value={{ user, signOut, refreshUser }}>
      <UploadProvider>
        <AudioProvider>
        <BrowserRouter>
          <Shell>
            <Routes>
              <Route path="/" element={<Navigate to="/photos" replace />} />
              <Route path="/photos" element={<PhotosPage />} />
              <Route path="/photos/albums" element={<AlbumsPage />} />
              <Route path="/photos/search" element={<PhotoSearchPage />} />
              <Route path="/photos/people" element={<PeoplePage />} />
              <Route path="/photos/people/:id" element={<PersonPage />} />
              <Route path="/photos/cleanup" element={<CleanupPage />} />
              <Route path="/photos/vault" element={<PhotoVaultPage />} />
              <Route path="/ask" element={<AskPage />} />
              <Route path="/photos/albums/:id" element={<AlbumPage />} />
              <Route path="/files/*" element={<FilesPage />} />
              <Route path="/duplicates" element={<FileDuplicatesPage />} />
              <Route path="/watch" element={<WatchHome />} />
              <Route path="/watch/c/:id" element={<LibraryPage />} />
              <Route path="/watch/series/:id" element={<SeriesPage />} />
              <Route path="/play/:id" element={<PlayerRoute />} />
              <Route path="/watch/link/:linkId/series/:seriesId" element={<LinkSeriesPage />} />
              <Route path="/watch/link/:linkId/:libraryId" element={<LinkLibraryPage />} />
              <Route path="/play/link/:linkId/:mediaId" element={<LinkPlayerPage />} />
              <Route path="/watch/parties" element={<PartiesPage />} />
              <Route path="/party/:id" element={<PartyRoute />} />
              <Route path="/movies" element={<Navigate to="/watch" replace />} />
              <Route path="/tv" element={<TvHome />} />
              <Route path="/tv/sources" element={<TvSourcesPage />} />
              <Route path="/tv/:source" element={<TvPage />} />
              <Route path="/tv/:source/movie/:id" element={<TvMoviePage />} />
              <Route path="/tv/:source/show/:id" element={<TvSeriesPage />} />
              <Route path="/tv/:source/play/:kind/:id" element={<TvPlayerPage />} />
              <Route path="/tv/:source/:tab" element={<TvPage />} />
              <Route path="/listen" element={<ListenHome />} />
              <Route path="/listen/albums" element={<MusicAlbumsPage />} />
              <Route path="/listen/album/:id" element={<AlbumDetailPage />} />
              <Route path="/listen/artists" element={<ArtistsPage />} />
              <Route path="/listen/artist" element={<ArtistDetailPage />} />
              <Route path="/listen/songs" element={<SongsPage />} />
              <Route path="/listen/playlists" element={<PlaylistsPage />} />
              <Route path="/listen/playlist/:id" element={<PlaylistDetailPage />} />
              <Route path="/listen/audiobooks" element={<AudiobooksPage />} />
              <Route path="/listen/book/:id" element={<AudiobookPage />} />
              <Route path="/quran" element={<QuranHomePage />} />
              <Route path="/quran/qari" element={<QariPage />} />
              <Route path="/quran/surahs" element={<SurahsPage />} />
              <Route path="/quran/surah/:n" element={<SurahPage />} />
              <Route path="/quran/namaz" element={<NamazPage />} />
              <Route path="/read" element={<ReadHome />} />
              <Route path="/read/c/:id" element={<ReadLibraryPage />} />
              <Route path="/read/series" element={<ReadSeriesPage />} />
              <Route path="/read/book/:id" element={<ReaderRoute />} />
              <Route path="/trash" element={<TrashPage />} />
              <Route path="/vault" element={<VaultPage />} />
              <Route path="/scan" element={<ScanPage />} />
              <Route path="/settings" element={<AdminPage />} />
              <Route path="*" element={<Navigate to="/photos" replace />} />
            </Routes>
          </Shell>
        </BrowserRouter>
        </AudioProvider>
      </UploadProvider>
    </AuthContext.Provider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const { pathname } = useLocation();
  const cinema = ["/watch", "/play", "/party", "/listen", "/tv"].some((p) => pathname.startsWith(p));
  useEffect(() => { document.documentElement.dataset.room = cinema ? "cinema" : "home"; }, [cinema]);
  // The side navigation can shrink to icons. Remembered per browser; on narrower screens it starts small.
  const [collapsed, setCollapsed] = useState(() => {
    try { const saved = localStorage.getItem(RAIL_KEY); if (saved !== null) return saved === "1"; } catch { /* private mode */ }
    return window.innerWidth < 1100;
  });
  useEffect(() => { document.documentElement.dataset.rail = collapsed ? "collapsed" : "open"; }, [collapsed]);
  const toggleRail = () => setCollapsed((c) => {
    try { localStorage.setItem(RAIL_KEY, c ? "0" : "1"); } catch { /* private mode */ }
    return !c;
  });
  const links = [
    { to: "/photos", label: tr("Photos"), icon: Images },
    { to: "/files", label: tr("Files"), icon: Folder },
    { to: "/watch", label: tr("Watch"), icon: Clapperboard },
    // IPTV channels carry no age ratings, so kids' profiles don't get Live TV
    ...(user.max_age == null ? [{ to: "/tv", label: tr("Live TV"), icon: Tv, desktop: false }] : []),
    { to: "/listen", label: tr("Listen"), icon: Headphones },
    { to: "/read", label: tr("Read"), icon: BookOpen },
    { to: "/quran", label: tr("Quran & Namaz"), short: tr("Quran"), icon: MoonStar },
    { to: "/trash", label: tr("Trash"), icon: Trash2, desktop: true },
    { to: "/settings", label: tr("Settings"), icon: Settings, desktop: true },
  ];
  useStickyHeads();
  return (
    <div className="shell">
      <nav className="rail" aria-label={tr("Main")}>
        <div className="brand">
          <HiveMark size={26} /><span className="rail-label">{tr("ZiraHive")}</span>
          <button className="icon rail-toggle" onClick={toggleRail} aria-expanded={!collapsed}
            aria-label={collapsed ? tr("Expand navigation") : tr("Collapse navigation")} title={collapsed ? tr("Expand navigation") : tr("Collapse navigation")}>
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>
        {links.map(({ to, label, short, icon: Icon, desktop }: { to: string; label: string; short?: string; icon: typeof Images; desktop?: boolean }) => (
          <NavLink key={to} to={to} className={desktop ? "desktop-only" : undefined}
            title={collapsed ? label : undefined} aria-label={collapsed ? label : undefined}>
            <Icon size={19} aria-hidden /> <span className="rail-label">{short
              ? <><span className="label-long">{label}</span><span className="label-short">{short}</span></> : label}</span></NavLink>
        ))}
        <div className="rail-foot">
          <span className="who" title={user.username}>{user.username}</span>
          <NotificationBell />
          <button className="icon" onClick={signOut} aria-label={tr("Sign out")} title={tr("Sign out")}><LogOut size={17} /></button>
        </div>
      </nav>
      <div className="mobile-top">
        <span className="brand-inline"><HiveMark size={22} />{" "}{tr("ZiraHive")}</span>
        <NavLink to="/trash" className="icon" aria-label={tr("Trash")}><Trash2 size={19} /></NavLink>
        <NavLink to="/settings" className="icon" aria-label={tr("Settings")}><Settings size={19} /></NavLink>
        <NotificationBell />
      </div>
      <main>{children}</main>
      <NowPlaying />
      <PrayerAlerts />
    </div>
  );
}

function SignIn({ firstRun, onSignedIn }: { firstRun: boolean; onSignedIn: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (firstRun && password.length < 8) { setError(tr("Use at least 8 characters for the password.")); return; }
    setBusy(true);
    try {
      const res = firstRun ? await api.setup(username, password) : await api.login(username, password, needCode ? code : undefined);
      onSignedIn(res.user);
    } catch (err) {
      if (err instanceof ApiError && err.code === "2fa_required") { setNeedCode(true); return; }
      setError(err instanceof ApiError ? err.message : tr("Can't reach the server. Check that ZiraHive is running."));
    } finally { setBusy(false); }
  };

  const withPasskey = async () => {
    setError("");
    setBusy(true);
    try {
      const { options, state } = await api.passkeyLoginOptions();
      const res = await api.passkeyLogin(state, await getPasskey(options));
      onSignedIn(res.user);
    } catch (err) {
      if (!cancelled(err)) setError(err instanceof ApiError ? err.message : tr("The passkey couldn't be used."));
    } finally { setBusy(false); }
  };

  return (
    <div className="signin">
      <form onSubmit={submit}>
        <div className="signin-mark"><HiveMark size={56} /></div>
        <h1>{firstRun ? tr("Set up your ZiraHive") : tr("Welcome home")}</h1>
        <p>{firstRun ? tr("Create the admin account. You can add family members afterwards.") : tr("Sign in to your photos, files and movies.")}</p>
        <label>{tr("Username")}<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus /></label>
        <label>{tr("Password")}<input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete={firstRun ? "new-password" : "current-password"} required /></label>
        {needCode && (
          <label>{tr("Code from your authenticator app")}<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code"
              placeholder={tr("123456, or a recovery code")} required autoFocus />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{firstRun ? tr("Create admin account") : needCode ? tr("Verify and sign in") : tr("Sign in")}</button>
        {!firstRun && !passkeyProblem() && (
          <>
            <p className="or muted">{tr("or")}</p>
            <button type="button" onClick={() => void withPasskey()} disabled={busy}>
              <Fingerprint size={17} aria-hidden />{" "}{tr("Sign in with a passkey")}</button>
          </>
        )}
        <button type="button" className="lang-switch" onClick={() => setLang(lang() === "bn" ? "en" : "bn")}
          lang={lang() === "bn" ? "en" : "bn"}>{lang() === "bn" ? "English" : "বাংলা"}</button>
      </form>
    </div>
  );
}
