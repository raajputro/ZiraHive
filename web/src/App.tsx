import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Images, Folder, Clapperboard, Trash2, Settings, LogOut } from "lucide-react";
import { api, ApiError, type User } from "./api";
import { UploadProvider } from "./uploads";
import { PrefsProvider } from "./prefs";
import NotificationBell from "./components/Notifications";
import PhotosPage from "./pages/Photos";
import AlbumsPage, { AlbumPage } from "./pages/Albums";
import PublicSharePage from "./pages/PublicShare";
import FilesPage from "./pages/Files";
import WatchHome, { LibraryPage } from "./pages/Watch";
import SeriesPage from "./pages/Series";
import PlayerRoute from "./pages/Player";
import TrashPage from "./pages/Trash";
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
              <Route path="/movies" element={<Navigate to="/watch" replace />} />
              <Route path="/trash" element={<TrashPage />} />
              <Route path="/settings" element={<AdminPage />} />
              <Route path="*" element={<Navigate to="/photos" replace />} />
            </Routes>
          </Shell>
        </BrowserRouter>
      </UploadProvider>
    </AuthContext.Provider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const { pathname } = useLocation();
  const cinema = pathname.startsWith("/watch") || pathname.startsWith("/play");
  useEffect(() => { document.documentElement.dataset.room = cinema ? "cinema" : "home"; }, [cinema]);
  const links = [
    { to: "/photos", label: "Photos", icon: Images },
    { to: "/files", label: "Files", icon: Folder },
    { to: "/watch", label: "Watch", icon: Clapperboard },
    { to: "/trash", label: "Trash", icon: Trash2 },
    { to: "/settings", label: "Settings", icon: Settings },
  ];
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand"><span lang="bn">ঘর</span> GharBox</div>
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to}><Icon size={19} aria-hidden /> <span>{label}</span></NavLink>
        ))}
        <div className="rail-foot">
          <span className="who">{user.username}</span>
          <NotificationBell />
          <button className="icon" onClick={signOut} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
        </div>
      </nav>
      <div className="mobile-top">
        <span className="brand-inline"><span lang="bn">ঘর</span> GharBox</span>
        <NotificationBell />
      </div>
      <main>{children}</main>
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
