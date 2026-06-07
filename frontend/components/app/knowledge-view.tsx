'use client';

import * as React from 'react';
import { cn } from '@/lib/shadcn/utils';

const UPLOADER_URL = process.env.NEXT_PUBLIC_UPLOADER_URL ?? 'http://localhost:8080';

type KbDoc = { id: string; category: string; topic: string; preview: string };
type KbUploaded = { source: string; chunks: number };

type KbResponse = {
  ok: boolean;
  index?: string;
  seeded?: KbDoc[];
  uploaded?: KbUploaded[];
  counts?: { seeded: number; uploaded: number };
};

export function KnowledgeView({ className }: { className?: string }) {
  const [data, setData] = React.useState<KbResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [status, setStatus] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const load = React.useCallback(async () => {
    try {
      const res = await fetch(`${UPLOADER_URL}/api/kb`);
      const json = (await res.json()) as KbResponse;
      setData(json);
      setError(null);
    } catch {
      setError(`Couldn't reach the knowledge service at ${UPLOADER_URL}. Is it running?`);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setStatus('Parsing & indexing…');
    try {
      const fd = new FormData();
      for (const f of Array.from(files)) fd.append('files', f);
      const res = await fetch(`${UPLOADER_URL}/api/ingest`, { method: 'POST', body: fd });
      const json = await res.json();
      if (json.ok) {
        setStatus(`Added ${json.total_chunks} chunks to the knowledge base.`);
        await load();
      } else {
        setStatus(json.error || 'Upload failed.');
      }
    } catch {
      setStatus('Upload failed — is the knowledge service running?');
    } finally {
      setBusy(false);
    }
  }

  const seeded = data?.seeded ?? [];
  const uploaded = data?.uploaded ?? [];

  return (
    <div className={cn('mx-auto w-full max-w-4xl px-6 py-8', className)}>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge Base</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          The lease, property handbook, and any documents you add. Mira grounds every answer in
          these — retrieved from Moss in under ten milliseconds.
        </p>
      </div>

      {/* Upload */}
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(e.dataTransfer.files);
        }}
        className="border-border bg-card hover:border-foreground/30 mb-8 cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors"
      >
        <p className="text-sm font-medium">
          {busy ? 'Working…' : 'Drag & drop, or click to add documents'}
        </p>
        <p className="text-muted-foreground mt-1 text-xs">PDF, text, or markdown</p>
        {status && <p className="text-muted-foreground mt-3 text-xs">{status}</p>}
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.markdown,text/plain"
          className="hidden"
          onChange={(e) => upload(e.target.files)}
        />
      </div>

      {error && (
        <div className="border-destructive/40 text-destructive mb-6 rounded-lg border p-3 text-sm">
          {error}
        </div>
      )}

      {uploaded.length > 0 && (
        <div className="mb-8">
          <h2 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
            Uploaded this session
          </h2>
          <div className="space-y-2">
            {uploaded.map((u, i) => (
              <div
                key={`${u.source}-${i}`}
                className="border-border bg-card flex items-center justify-between rounded-lg border px-4 py-2 text-sm"
              >
                <span className="truncate">{u.source}</span>
                <span className="text-muted-foreground text-xs">{u.chunks} chunks</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <h2 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
        Lease &amp; handbook ({seeded.length})
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {seeded.map((d) => (
          <div key={d.id} className="border-border bg-card rounded-lg border p-4">
            <div className="mb-1 flex items-center gap-2">
              <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                {d.category}
              </span>
              {d.topic && <span className="text-muted-foreground text-xs">{d.topic}</span>}
            </div>
            <p className="text-foreground/80 line-clamp-3 text-sm leading-snug">{d.preview}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
