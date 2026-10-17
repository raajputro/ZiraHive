// Passkeys in the browser: turning the server's JSON options into what navigator.credentials
// wants (ArrayBuffers), and the answer back into JSON. Done by hand for older browsers.
/* eslint-disable @typescript-eslint/no-explicit-any */

const toBytes = (s: string) => {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
};
const toB64u = (buf: ArrayBuffer | null) => {
  if (!buf) return null;
  let s = "";
  new Uint8Array(buf).forEach((x) => { s += String.fromCharCode(x); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

/** Why passkeys can't be used on this page, or null. */
export function passkeyProblem(): "unsupported" | "insecure" | null {
  if (!window.isSecureContext) return "insecure";
  if (!window.PublicKeyCredential || !navigator.credentials) return "unsupported";
  return null;
}

export async function createPasskey(options: any): Promise<unknown> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: toBytes(options.challenge),
    user: { ...options.user, id: toBytes(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((c: any) => ({ ...c, id: toBytes(c.id) })),
  };
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new DOMException("cancelled", "NotAllowedError");
  const r = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: toB64u(r.clientDataJSON), attestationObject: toB64u(r.attestationObject),
      transports: typeof r.getTransports === "function" ? r.getTransports() : undefined,
    },
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
  };
}

export async function getPasskey(options: any): Promise<unknown> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: toBytes(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((c: any) => ({ ...c, id: toBytes(c.id) })),
  };
  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new DOMException("cancelled", "NotAllowedError");
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
    response: {
      clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData),
      signature: toB64u(r.signature), userHandle: toB64u(r.userHandle),
    },
    clientExtensionResults: cred.getClientExtensionResults?.() ?? {},
  };
}

/** True when the person closed the passkey prompt (not an error worth showing). */
export const cancelled = (e: unknown) => e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "AbortError");

/** A name for the passkey from the device it was made on. */
export function deviceName(): string {
  const ua = navigator.userAgent;
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone" : /Mac OS X/.test(ua) ? "Mac"
    : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari" : "";
  return [os, browser].filter(Boolean).join(", ");
}
