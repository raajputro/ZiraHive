import { useEffect, useState } from "react";
import { Fingerprint, Trash2 } from "lucide-react";
import { api, ApiError, type Passkey } from "../api";
import { cancelled, createPasskey, deviceName, passkeyProblem } from "../passkeys";
import { locale, t as tr } from "../i18n";

export default function PasskeysPanel() {
  const [keys, setKeys] = useState<Passkey[]>([]);
  const [name, setName] = useState(deviceName);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const problem = passkeyProblem();
  const here = location.hostname;

  const load = () => api.passkeys().then(setKeys).catch(() => undefined);
  useEffect(() => { void load(); }, []);

  const add = async () => {
    setMsg("");
    setBusy(true);
    try {
      const { options, state } = await api.passkeyRegisterOptions();
      const credential = await createPasskey(options);
      const pk = await api.passkeyRegister(state, credential, name.trim());
      setMsg(tr("Passkey \"{name}\" added. Next time, choose \"Sign in with a passkey\".", { name: pk.name }));
      void load();
    } catch (e) {
      if (cancelled(e)) setMsg("");
      else setMsg(e instanceof ApiError ? e.message : e instanceof DOMException && e.name === "InvalidStateError"
        ? tr("This device already has a passkey for your account.") : tr("The passkey couldn't be made."));
    } finally { setBusy(false); }
  };

  const remove = async (p: Passkey) => {
    if (!confirm(tr("Remove the passkey \"{name}\"? Delete it from the device too, in its password settings.", { name: p.name }))) return;
    await api.removePasskey(p.id).catch(() => undefined);
    void load();
  };

  return (
    <section className="panel passkeys">
      <h2><Fingerprint size={18} aria-hidden />{" "}{tr("Passkeys")}</h2>
      <p className="muted">{tr("Sign in with your phone's or laptop's fingerprint, face or screen lock instead of a password. A passkey can't be guessed or stolen by a fake website.")}</p>
      {keys.length > 0 && (
        <ul className="passkey-list">
          {keys.map((p) => (
            <li key={p.id}>
              <div>
                <strong>{p.name}</strong>
                <span className="muted small">
                  {p.rp_id}{" · "}{p.last_used_at
                    ? tr("last used {when}", { when: new Date(p.last_used_at).toLocaleDateString(locale()) })
                    : tr("not used yet")}
                </span>
              </div>
              <button className="icon" onClick={() => void remove(p)} aria-label={tr("Remove {name}", { name: p.name })}><Trash2 size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      {problem === "insecure" ? (
        <p className="notice">{tr("Passkeys need a secure address. Open GharBox at your https:// address (or http://localhost on the server PC) to add one.")}</p>
      ) : problem === "unsupported" ? (
        <p className="notice">{tr("This browser can't use passkeys. Try a recent Chrome, Edge, Safari or Firefox.")}</p>
      ) : (
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); void add(); }}>
          <label>{tr("Name for this device")}<input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder={tr("For example: Mahbub's phone")} /></label>
          <button className="primary" disabled={busy}>{tr("Add a passkey")}</button>
        </form>
      )}
      {!problem && <p className="muted small">{tr("A passkey works on the address it was made on, here {host}. Add one on each address you use.", { host: here })}</p>}
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}
