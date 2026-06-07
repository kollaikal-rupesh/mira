import "dotenv/config"; // load .env before reading process.env (bun does this natively)
import { createServer, type IncomingMessage } from "node:http";
import { Spectrum, type SpectrumInstance } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

// Spectrum (Photon) outbound iMessage service.
//
// The Wayline voice agent (Python, LiveKit) resolves a ticket "by text": it
// POSTs { to, body } here and we send it as an iMessage via the spectrum-ts SDK.
// Photon has no Python/REST send endpoint, so this tiny service is the bridge.
//
// Env (.env):
//   PROJECT_ID, PROJECT_SECRET   — Photon dashboard → project Settings (required to send)
//   ESCALATE_SHARED_SECRET       — optional; if set, callers must pass x-escalate-secret
//   SEND_PORT                    — HTTP port (default 8787)

const PROJECT_ID = process.env.PROJECT_ID;
const PROJECT_SECRET = process.env.PROJECT_SECRET;
const SHARED_SECRET = process.env.ESCALATE_SHARED_SECRET;
const PORT = Number(process.env.SEND_PORT ?? process.env.PORT ?? 8787);

// Lazily initialize Spectrum and cache it. The HTTP server still starts without
// credentials so the agent degrades gracefully (503) instead of crashing.
let appPromise: Promise<SpectrumInstance> | null = null;

function getApp(): Promise<SpectrumInstance> {
  if (!PROJECT_ID || !PROJECT_SECRET) {
    throw new Error("Photon not configured (PROJECT_ID / PROJECT_SECRET).");
  }
  if (!appPromise) {
    appPromise = Spectrum({
      projectId: PROJECT_ID,
      projectSecret: PROJECT_SECRET,
      providers: [imessage.config()],
    }).catch((err) => {
      appPromise = null; // allow retry on next request
      throw err;
    });
  }
  return appPromise;
}

async function sendIMessage(to: string, body: string): Promise<void> {
  const app = await getApp();
  const im = imessage(app);
  const recipient = await im.user(to);
  const space = await im.space(recipient);
  await space.send(body);
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c as Buffer));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

const server = createServer(async (req, res) => {
  const json = (status: number, payload: unknown) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(payload));
  };

  if (req.method === "GET" && req.url === "/health") {
    return json(200, { ok: true, configured: Boolean(PROJECT_ID && PROJECT_SECRET) });
  }

  if (req.method !== "POST" || req.url !== "/send") {
    return json(404, { ok: false, error: "POST /send" });
  }

  if (SHARED_SECRET && req.headers["x-escalate-secret"] !== SHARED_SECRET) {
    return json(401, { ok: false, error: "unauthorized" });
  }

  let to: unknown;
  let body: unknown;
  try {
    const parsed = JSON.parse(await readBody(req));
    to = parsed?.to;
    body = parsed?.body;
  } catch {
    return json(400, { ok: false, error: "invalid JSON" });
  }

  if (typeof to !== "string" || !to || typeof body !== "string" || !body) {
    return json(400, { ok: false, error: "expected { to: E.164 string, body: string }" });
  }

  if (!PROJECT_ID || !PROJECT_SECRET) {
    return json(503, { ok: false, error: "photon not configured" });
  }

  try {
    await sendIMessage(to, body);
    return json(200, { ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "send failed";
    console.error("iMessage send failed:", message);
    return json(502, { ok: false, error: message });
  }
});

server.listen(PORT, () => {
  const ready =
    PROJECT_ID && PROJECT_SECRET ? "configured" : "NOT configured (set PROJECT_ID/SECRET in .env)";
  console.log(`Spectrum send service on http://localhost:${PORT} — Photon ${ready}`);
});

// Inbound channel: residents text Mira's iMessage line and ask anything about
// the property. Each text is answered by the Python /api/answer endpoint
// (Moss-grounded, same brain as the voice agent), then replied in-thread.
const ANSWER_URL = process.env.ANSWER_URL ?? "http://localhost:8080/api/answer";

async function runInbound(): Promise<void> {
  if (!PROJECT_ID || !PROJECT_SECRET) {
    console.log("Inbound loop disabled (Photon not configured).");
    return;
  }
  const app = await getApp();
  console.log("Mira iMessage inbound loop is live — text the line to ask about the property.");
  for await (const [space, message] of app.messages) {
    if (message.content.type !== "text") continue;
    const question = message.content.text;
    let reply = "Sorry, I couldn't reach the knowledge base just now. Please try again.";
    try {
      const res = await fetch(ANSWER_URL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = (await res.json()) as { ok?: boolean; answer?: string };
      if (data?.ok && data?.answer) reply = data.answer;
    } catch (err) {
      console.error("answer fetch failed:", err instanceof Error ? err.message : err);
    }
    try {
      await space.send(reply);
    } catch (err) {
      console.error("reply send failed:", err instanceof Error ? err.message : err);
    }
  }
}

runInbound().catch((err) => console.error("inbound loop error:", err));
