import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { request } from "./lib.js";

/** Owner sign-in. The server checks the password against a scrypt hash and sets an HttpOnly session cookie. */
export function Login({ onDone }) {
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await request("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pw }) }, 30);
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || `Sign-in failed (${r.status})`);
      setPw(""); onDone();
    } catch (e2) { setErr(String(e2.message || e2)); } finally { setBusy(false); }
  };
  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <form onSubmit={submit} className="space-y-3 rounded border border-subtle bg-surface p-5">
        <h1 className="flex items-center gap-2 text-section font-bold"><Lock size={18} aria-hidden /> TR8DE</h1>
        <p className="text-sm text-ink-2">Sign in to the owner console.</p>
        <label className="block text-sm">Username
          <input className="mt-1 w-full rounded border border-subtle bg-canvas px-2 py-1.5" autoComplete="username"
            value={user} onChange={(e) => setUser(e.target.value)} required autoFocus /></label>
        <label className="block text-sm">Password
          <input type="password" className="mt-1 w-full rounded border border-subtle bg-canvas px-2 py-1.5"
            autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
        {err && <p role="alert" className="text-sm text-bad">{err}</p>}
        <button disabled={busy} className="min-h-[40px] w-full rounded bg-ink px-3 font-semibold text-canvas disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

export async function logout() {
  await request("/api/logout", { method: "POST" }).catch(() => {});
  window.location.reload();
}

/** Shows the page only after the server confirms a session; a 401 anywhere brings the sign-in back. */
export function Gate({ children }) {
  const [state, setState] = useState("checking");
  const check = () => request("/api/session").then((r) => r.json())
    .then((j) => setState(j.signed_in ? "in" : "out")).catch((e) => setState(String(e.message || e)));
  useEffect(() => {
    check();
    const out = () => setState("out");
    window.addEventListener("tiwala-signin", out);
    return () => window.removeEventListener("tiwala-signin", out);
  }, []);
  if (state === "in") return children;
  if (state === "out") return <Login onDone={() => setState("in")} />;
  if (state === "checking") return null;
  return <p role="alert" className="m-6 rounded border border-bad p-3 text-sm text-bad">{state}</p>;
}
