import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { request } from "./lib.js";
import { Brand } from "./components/Shell.jsx";

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
    <main className="grid min-h-[100dvh] place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-[#414e36] bg-[#1b2218] p-7 shadow-[0_30px_80px_#0008]">
        <Brand />
        <p className="flex items-center gap-2 text-cap text-ink-2"><Lock size={14} aria-hidden /> Sign in to the owner console.</p>
        <details className="text-sm text-ink-2">
          <summary className="cursor-pointer">Where do I get my login?</summary>
          <p className="mt-2">Local demo: username <strong>demo</strong>. Copy the password from your startup
            terminal under “6/6 Ready”, or from .local-demo/login.txt. It changes each demo run.</p>
          <p className="mt-2">Live Sepolia: username <strong>owner</strong> unless changed. Use the password
            you chose in the terminal during live setup. For a hosted instance, ask its operator for access.</p>
        </details>
        <label className="block text-cap text-ink-2">Username
          <input className="mt-1.5 w-full rounded-md border border-[#48593a] bg-[#11180e] px-3 py-2.5 text-sm text-ink" autoComplete="username"
            maxLength={64} value={user} onChange={(e) => setUser(e.target.value)} required autoFocus /></label>
        <label className="block text-cap text-ink-2">Password
          <input type="password" className="mt-1.5 w-full rounded-md border border-[#48593a] bg-[#11180e] px-3 py-2.5 text-sm text-ink"
            autoComplete="current-password" maxLength={256} value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
        {err && <p role="alert" className="text-cap text-bad">{err}</p>}
        <button disabled={busy} className="min-h-[40px] w-full rounded-md bg-accent px-3 text-sm font-semibold text-accent-deep hover:bg-[#d9edbc] disabled:opacity-60">
          {busy ? "Signing in…" : "Sign in"}</button>
        <p className="text-micro text-ink-2">Agents propose. Policy checks. You approve when required. The contract enforces.</p>
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
