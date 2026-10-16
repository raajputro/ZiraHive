import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Images, Folder, Clapperboard, Headphones, BookOpen, Trash2, Settings, LogOut } from "lucide-react";
import { api, ApiError, type User } from "./api";
import { UploadProvider } from "./uploads";
import { PrefsProvider } from "./prefs";
import { AudioProvider } from "./audio";
import NowPlaying from "./components/NowPlaying";
import NotificationBell from "./components/Notifications";
import PhotosPage from "./pages/Photos";
import AlbumsPage, { AlbumPage } from "./pages/Albums";
import PublicSharePage from "./pages/PublicShare";
import FilesPage from "./pages/Files";
import WatchHome, { LibraryPage } from "./pages/Watch";
import SeriesPage from "./pages/Series";
import PlayerRoute from "./pages/Player";
import PartyRoute from "./pages/Party";
import PartiesPage from "./pages/Parties";
import TrashPage from "./pages/Trash";
import { AlbumDetailPage, AlbumsPage as MusicAlbumsPage, ArtistDetailPage, ArtistsPage, AudiobookPage, AudiobooksPage, ListenHome,
  PlaylistDetailPage, PlaylistsPage, SongsPage } from "./pages/Listen";
import { ReadHome, ReadLibraryPage, ReadSeriesPage } from "./pages/Read";
import ReaderRoute from "./pages/Reader";
import AdminPage from "./pages/Admin";

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
    api.me().then(setUser).catch(async () => {
      setNeedsSetup((await api.setupStatus().catch(() => ({ needs_setup: false }))).needs_setup);
      setUser(null);
    });
    const onSignedOut = () => setUser(null);
    window.addEventListener("gharbox:signed-out", onSignedOut);
    return () => window.removeEventListener("gharbox:signed-out", onSignedOut);
  }, []);

  if (user === undefined) return <div className="boot" aria-busy="true" />;
  if (user === null) return <SignIn firstRun={needsSetup} onSignedIn={(u) => { setNeedsSetup(false); setUser(u); }} />;

  const signOut = () => { void api.logout().finally(() => setUser(null)); };
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
              <Route path="/photos/albums/:id" element={<AlbumPage />} />
              <Route path="/files/*" element={<FilesPage />} />
              <Route path="/watch" element={<WatchHome />} />
              <Route path="/watch/c/:id" element={<LibraryPage />} />
              <Route path="/watch/series/:id" element={<SeriesPage />} />
              <Route path="/play/:id" element={<PlayerRoute />} />
              <Route path="/watch/parties" element={<PartiesPage />} />
              <Route path="/party/:id" element={<PartyRoute />} />
              <Route path="/movies" element={<Navigate to="/watch" replace />} />
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
              <Route path="/read" element={<ReadHome />} />
              <Route path="/read/c/:id" element={<ReadLibraryPage />} />
              <Route path="/read/series" element={<ReadSeriesPage />} />
              <Route path="/read/book/:id" element={<ReaderRoute />} />
              <Route path="/trash" element={<TrashPage />} />
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
  const cinema = ["/watch", "/play", "/party", "/listen"].some((p) => pathname.startsWith(p));
  useEffect(() => { document.documentElement.dataset.room = cinema ? "cinema" : "home"; }, [cinema]);
  const links = [
    { to: "/photos", label: "Photos", icon: Images },
    { to: "/files", label: "Files", icon: Folder },
    { to: "/watch", label: "Watch", icon: Clapperboard },
    { to: "/listen", label: "Listen", icon: Headphones },
    { to: "/read", label: "Read", icon: BookOpen },
    { to: "/trash", label: "Trash", icon: Trash2, desktop: true },
    { to: "/settings", label: "Settings", icon: Settings, desktop: true },
  ];
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand"><span lang="bn">ঘর</span> GharBox</div>
        {links.map(({ to, label, icon: Icon, desktop }) => (
          <NavLink key={to} to={to} className={desktop ? "desktop-only" : undefined}><Icon size={19} aria-hidden /> <span>{label}</span></NavLink>
        ))}
        <div className="rail-foot">
          <span className="who">{user.username}</span>
          <NotificationBell />
          <button className="icon" onClick={signOut} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
        </div>
      </nav>
      <div className="mobile-top">
        <span className="brand-inline"><span lang="bn">ঘর</span> GharBox</span>
        <NavLink to="/trash" className="icon" aria-label="Trash"><Trash2 size={19} /></NavLink>
        <NavLink to="/settings" className="icon" aria-label="Settings"><Settings size={19} /></NavLink>
        <NotificationBell />
      </div>
      <main>{children}</main>
      <NowPlaying />
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
    if (firstRun && password.length < 8) { setError("Use at least 8 characters for the password."); return; }
    setBusy(true);
    try {
      const res = firstRun ? await api.setup(username, password) : await api.login(username, password, needCode ? code : undefined);
      onSignedIn(res.user);
    } catch (err) {
      if (err instanceof ApiError && err.code === "2fa_required") { setNeedCode(true); return; }
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check that GharBox is running.");
    } finally { setBusy(false); }
  };

  return (
    <div className="signin">
      <form onSubmit={submit}>
        <div className="signin-mark" lang="bn" aria-hidden>ঘর</div>
        <h1>{firstRun ? "Set up your GharBox" : "Welcome home"}</h1>
        <p>{firstRun ? "Create the admin account. You can add family members afterwards." : "Sign in to your photos, files and movies."}</p>
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete={firstRun ? "new-password" : "current-password"} required /></label>
        {needCode && (
          <label>Code from your authenticator app
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code"
              placeholder="123456, or a recovery code" required autoFocus />
          </label>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{firstRun ? "Create admin account" : needCode ? "Verify and sign in" : "Sign in"}</button>
      </form>
    </div>
  );
}
