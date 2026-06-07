import { NextResponse } from 'next/server';
import { Spectrum, type SpectrumInstance } from 'spectrum-ts';
import { imessage } from 'spectrum-ts/providers/imessage';

// Photon (Spectrum) iMessage bridge.
//
// The voice agent is Python and Photon's send path is TypeScript-only (there is
// no REST send endpoint — see https://photon.codes/docs). So this Next.js route
// is the bridge: the Python agent POSTs a dossier/receipt here over HTTP, and we
// send it as an iMessage via the spectrum-ts SDK.
//
// Server-only env (set in frontend/.env.local — never NEXT_PUBLIC_*):
//   PHOTON_PROJECT_ID, PHOTON_PROJECT_SECRET  — Photon dashboard → project Settings
//   ESCALATE_SHARED_SECRET (optional)         — must match the agent's header

export const runtime = 'nodejs';
export const revalidate = 0;

const PROJECT_ID = process.env.PHOTON_PROJECT_ID;
const PROJECT_SECRET = process.env.PHOTON_PROJECT_SECRET;
const SHARED_SECRET = process.env.ESCALATE_SHARED_SECRET;

// Cache the Spectrum app across requests — initialization is expensive and the
// credentials don't change at runtime. A single in-flight promise is reused.
let appPromise: Promise<SpectrumInstance> | null = null;

function getApp(): Promise<SpectrumInstance> {
  if (!PROJECT_ID || !PROJECT_SECRET) {
    throw new Error('Photon is not configured (PHOTON_PROJECT_ID / PHOTON_PROJECT_SECRET).');
  }
  if (!appPromise) {
    appPromise = Spectrum({
      projectId: PROJECT_ID,
      projectSecret: PROJECT_SECRET,
      providers: [imessage.config()],
    }).catch((err) => {
      // Reset so the next request can retry a failed init.
      appPromise = null;
      throw err;
    });
  }
  return appPromise;
}

export async function POST(req: Request) {
  // Optional shared-secret gate so only our agent can trigger sends.
  if (SHARED_SECRET && req.headers.get('x-escalate-secret') !== SHARED_SECRET) {
    return NextResponse.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  }

  let to: unknown;
  let body: unknown;
  try {
    const json = await req.json();
    to = json?.to;
    body = json?.body;
  } catch {
    return NextResponse.json({ ok: false, error: 'invalid JSON' }, { status: 400 });
  }

  if (typeof to !== 'string' || !to || typeof body !== 'string' || !body) {
    return NextResponse.json(
      { ok: false, error: 'expected { to: E.164 string, body: string }' },
      { status: 400 }
    );
  }

  if (!PROJECT_ID || !PROJECT_SECRET) {
    // Degrade gracefully: tell the agent we couldn't send so it reads aloud.
    return NextResponse.json({ ok: false, error: 'photon not configured' }, { status: 503 });
  }

  try {
    const app = await getApp();
    const im = imessage(app);
    const recipient = await im.user(to);
    const space = await im.space(recipient);
    await space.send(body);
    return NextResponse.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'send failed';
    console.error('iMessage send failed:', message);
    return NextResponse.json({ ok: false, error: message }, { status: 502 });
  }
}
