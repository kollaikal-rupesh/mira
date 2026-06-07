'use client';

import * as React from 'react';
import type { MossContextEvent } from '@/hooks/useMossContextEvents';
import { cn } from '@/lib/shadcn/utils';

const STORAGE_KEY = 'mira_call_log';

type LogEntry = {
  id: string;
  query: string;
  topMatch: string;
  score?: number;
  timeTakenMs?: number | null;
  timestamp: number;
};

function loadStored(): LogEntry[] {
  if (typeof window === 'undefined') return [];
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function fmtTime(ts: number): string {
  try {
    return new Date(ts).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

/**
 * Call Logs — a timeline of what Mira looked up on calls: each Moss retrieval
 * with the query, the top matched document, relevance, and latency. Live events
 * are merged with a localStorage history so past calls persist across reloads.
 */
export function CallLogsView({
  liveEvents,
  className,
}: {
  liveEvents: MossContextEvent[];
  className?: string;
}) {
  const [stored, setStored] = React.useState<LogEntry[]>([]);

  React.useEffect(() => {
    setStored(loadStored());
  }, []);

  // Merge live events into storage (dedup by id).
  React.useEffect(() => {
    if (liveEvents.length === 0) return;
    setStored((prev) => {
      const seen = new Set(prev.map((e) => e.id));
      const fresh: LogEntry[] = liveEvents
        .filter((e) => !seen.has(e.id))
        .map((e) => ({
          id: e.id,
          query: e.query,
          topMatch: e.matches[0]?.text?.slice(0, 200) ?? '',
          score: e.matches[0]?.score,
          timeTakenMs: e.timeTakenMs,
          timestamp: e.timestamp,
        }));
      if (fresh.length === 0) return prev;
      const next = [...prev, ...fresh].slice(-200);
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* ignore quota */
      }
      return next;
    });
  }, [liveEvents]);

  const entries = React.useMemo(
    () => [...stored].sort((a, b) => b.timestamp - a.timestamp),
    [stored]
  );

  function clearLog() {
    window.localStorage.removeItem(STORAGE_KEY);
    setStored([]);
  }

  return (
    <div className={cn('mx-auto w-full max-w-4xl px-6 py-8', className)}>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Call Logs</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Every knowledge lookup Mira made on a call — query, the document it grounded on,
            relevance, and Moss latency.
          </p>
        </div>
        {entries.length > 0 && (
          <button
            onClick={clearLog}
            className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4"
          >
            Clear
          </button>
        )}
      </div>

      {entries.length === 0 ? (
        <div className="border-border text-muted-foreground rounded-xl border border-dashed p-10 text-center text-sm">
          No calls logged yet. Start a call and ask Mira a question — every lookup shows up here.
        </div>
      ) : (
        <div className="relative space-y-3 before:absolute before:top-2 before:bottom-2 before:left-[7px] before:w-px before:bg-border">
          {entries.map((e) => (
            <div key={e.id} className="relative pl-6">
              <span className="bg-foreground absolute top-2 left-0 size-[15px] rounded-full border-4 border-background" />
              <div className="border-border bg-card rounded-lg border p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">{e.query}</p>
                  <div className="flex shrink-0 items-center gap-2">
                    {typeof e.timeTakenMs === 'number' && (
                      <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 font-mono text-[10px]">
                        {e.timeTakenMs.toFixed(0)} ms
                      </span>
                    )}
                    <span className="text-muted-foreground text-[10px]">{fmtTime(e.timestamp)}</span>
                  </div>
                </div>
                {e.topMatch && (
                  <p className="text-muted-foreground mt-2 line-clamp-2 text-xs leading-snug">
                    {e.topMatch}
                    {typeof e.score === 'number' && (
                      <span className="ml-1 opacity-70">· relevance {e.score.toFixed(2)}</span>
                    )}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
