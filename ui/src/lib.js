export const EXPLORER = "https://sepolia.etherscan.io";
export const txUrl = (h) => `${EXPLORER}/tx/${h}`;
export const addrUrl = (a) => `${EXPLORER}/address/${a}`;
export const chunk = (a) => (a ? "0x" + a.slice(2).match(/.{1,4}/g).join(" ") : "");
export const short = (h, n = 10) => (h ? `${h.slice(0, n)}…${h.slice(-4)}` : "");
export const peso = (v, dp = 0) =>
  v == null ? "n/a" : "₱" + Number(v).toLocaleString("en-PH", { minimumFractionDigits: dp, maximumFractionDigits: dp });

const fmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});
export const when = (ts) => (ts ? fmt.format(new Date(ts * 1000)).replace(",", "") : "");
export const day = (ts) => when(ts).slice(0, 10);

export const KIND = {
  create_deal: "Create escrow deal",
  release_down_payment: "Release down payment",
  release_balance: "Release balance",
  cancel_deal: "Cancel and refund",
};
export const RULE = { overdue_cancel: "Overdue past grace", attested_release: "Owner attested delivery" };

export function query() {
  const p = new URLSearchParams(window.location.search);
  return p.get("fixture");
}
const q = (fixture) => (fixture ? `?fixture=${encodeURIComponent(fixture)}` : "");

export const SERVER_DOWN = "Cannot reach the Tiwala server. It is not running or it restarted. Start it with: "
  + "cd agent && ../.venv/bin/uvicorn console.server:app --port 8000, then reload this page.";

/** fetch with a clear message for a dead server or a slow model/chain instead of a bare "Load failed". */
export async function request(path, opts = {}, timeoutS = 120) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutS * 1000);
  try {
    const r = await fetch(path, { ...opts, headers: { ...(opts.headers || {}), "X-Tiwala": "1" }, signal: ctl.signal });
    if (r.status === 401 && path !== "/api/login") {
      window.dispatchEvent(new Event("tiwala-signin"));
      throw new Error("Please sign in.");
    }
    return r;
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error(`No answer from the server after ${timeoutS} s. The model or the chain RPC may be slow; try again.`);
    }
    throw new Error(SERVER_DOWN);
  } finally {
    clearTimeout(t);
  }
}

export async function getJSON(path, fixture) {
  const r = await request(path + q(fixture));
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}
export async function postJSON(path, fixture, body) {
  const r = await request(path + q(fixture), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

/** POST /api/message and read the SSE stream: onStep per event, resolves with the reply payload. */
export async function sendMessage(text, fixture, onStep) {
  const r = await request("/api/message" + q(fixture), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  }, 300);
  if (!r.ok || !r.body) throw new Error(`/api/message: ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "", result = null;
  for (;;) {
    const { value, done } = await reader.read().catch(() => { throw new Error(SERVER_DOWN); });
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const kind = /^event: (.+)$/m.exec(chunk)?.[1];
      const data = JSON.parse(/^data: (.+)$/m.exec(chunk)?.[1] || "null");
      if (kind === "step") onStep(data);
      else if (kind === "reply") result = data;
      else if (kind === "error") throw new Error(data.error);
    }
  }
  return result;
}

/** "down payment: you said 50%, action uses 25%" -> {field, said, drafted} */
export function parseMismatch(s) {
  const m = /^(.+?): you said (.+?), action uses (.+)$/.exec(s);
  return m ? { field: m[1], said: m[2], drafted: m[3] } : { field: s, said: "", drafted: "" };
}
