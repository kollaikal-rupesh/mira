'use client';

import * as React from 'react';
import { cn } from '@/lib/shadcn/utils';

const UPLOADER_URL = process.env.NEXT_PUBLIC_UPLOADER_URL ?? 'http://localhost:8080';

type WorkOrder = {
  id: string;
  summary: string;
  urgency: 'routine' | 'emergency';
  channel: string;
  tenant_id?: string | null;
  unit?: string | null;
  status: string;
  created_at: string;
};

type WorkOrdersResponse = {
  ok: boolean;
  orders?: WorkOrder[];
  count?: number;
};

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], {
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
 * Work Orders — every maintenance ticket Mira has opened, whether the resident
 * called (voice) or texted. Reads the shared store the agent and text channel
 * both write to, via the knowledge service's `/api/work-orders`.
 */
export function WorkOrdersView({ className }: { className?: string }) {
  const [orders, setOrders] = React.useState<WorkOrder[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loaded, setLoaded] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const res = await fetch(`${UPLOADER_URL}/api/work-orders`);
      const json = (await res.json()) as WorkOrdersResponse;
      setOrders(json.orders ?? []);
      setError(null);
    } catch {
      setError(`Couldn't reach the work-order service at ${UPLOADER_URL}. Is it running?`);
    } finally {
      setLoaded(true);
    }
  }, []);

  React.useEffect(() => {
    load();
    // Poll so tickets opened mid-call show up without a manual refresh.
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className={cn('mx-auto w-full max-w-4xl px-6 py-8', className)}>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Work Orders</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Maintenance tickets Mira opened for residents — from calls and texts alike. Emergencies
            are dispatched immediately and escalated to the property manager.
          </p>
        </div>
        <button
          onClick={load}
          className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="border-destructive/40 text-destructive mb-6 rounded-lg border p-3 text-sm">
          {error}
        </div>
      )}

      {loaded && !error && orders.length === 0 ? (
        <div className="border-border text-muted-foreground rounded-xl border border-dashed p-10 text-center text-sm">
          No work orders yet. When a resident reports something broken — by call or text — Mira
          opens a ticket and it shows up here.
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map((o) => (
            <div key={o.id} className="border-border bg-card rounded-lg border p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-medium">{o.id}</span>
                    {o.urgency === 'emergency' ? (
                      <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-red-600 uppercase dark:text-red-400">
                        Emergency
                      </span>
                    ) : (
                      <span className="bg-secondary text-secondary-foreground rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                        Routine
                      </span>
                    )}
                    <span className="text-muted-foreground border-border rounded border px-1.5 py-0.5 text-[10px] tracking-wide uppercase">
                      {o.channel}
                    </span>
                    {o.unit && <span className="text-muted-foreground text-xs">{o.unit}</span>}
                  </div>
                  <p className="text-foreground/90 text-sm leading-snug">{o.summary}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-muted-foreground text-[10px]">{fmtTime(o.created_at)}</span>
                  <span className="text-muted-foreground text-[10px] capitalize">{o.status}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
