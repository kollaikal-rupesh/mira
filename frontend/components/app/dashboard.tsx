'use client';

import * as React from 'react';
import { useSessionContext } from '@livekit/components-react';
import type { AppConfig } from '@/app-config';
import { CallLogsView } from '@/components/app/call-logs-view';
import { KnowledgeView } from '@/components/app/knowledge-view';
import { ViewController } from '@/components/app/view-controller';
import { useMossContextEvents } from '@/hooks/useMossContextEvents';
import { cn } from '@/lib/shadcn/utils';

type View = 'call' | 'logs' | 'kb';

const NAV: { key: View; label: string }[] = [
  { key: 'call', label: 'Call' },
  { key: 'logs', label: 'Call Logs' },
  { key: 'kb', label: 'Knowledge' },
];

interface DashboardProps {
  appConfig: AppConfig;
}

export function Dashboard({ appConfig }: DashboardProps) {
  const [view, setView] = React.useState<View>('call');
  const liveEvents = useMossContextEvents(100);
  const { isConnected } = useSessionContext();

  return (
    <div className="bg-background text-foreground h-svh">
      {/* Sidebar */}
      <aside className="border-border bg-background/80 fixed top-0 left-0 z-50 flex h-svh w-56 flex-col border-r px-3 py-5 backdrop-blur">
        <div className="mb-7 flex items-center gap-2 px-2">
          <span className="text-lg font-semibold tracking-tight">Mira</span>
          <span
            className={cn(
              'ml-auto inline-flex items-center gap-1.5 text-[10px]',
              isConnected ? 'text-green-600 dark:text-green-500' : 'text-muted-foreground'
            )}
          >
            <span
              className={cn(
                'inline-block size-2 rounded-full',
                isConnected ? 'bg-green-500' : 'bg-muted-foreground/40'
              )}
            />
            {isConnected ? 'on call' : 'idle'}
          </span>
        </div>

        <nav className="space-y-1">
          {NAV.map((n) => (
            <button
              key={n.key}
              onClick={() => setView(n.key)}
              className={cn(
                'flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors',
                view === n.key
                  ? 'bg-secondary text-secondary-foreground font-medium'
                  : 'text-muted-foreground hover:bg-secondary/50'
              )}
            >
              <span>{n.label}</span>
              {n.key === 'logs' && liveEvents.length > 0 && (
                <span className="text-muted-foreground text-xs">{liveEvents.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="text-muted-foreground mt-auto px-3 text-[10px] leading-relaxed">
          {appConfig.companyName} · grounded by Moss
          <br />
          on LiveKit
        </div>
      </aside>

      {/* Content */}
      <div className="h-svh pl-56">
        {view === 'call' && (
          <div className="grid h-svh place-content-center">
            <ViewController appConfig={appConfig} />
          </div>
        )}
        {view === 'logs' && (
          <div className="h-svh overflow-y-auto">
            <CallLogsView liveEvents={liveEvents} />
          </div>
        )}
        {view === 'kb' && (
          <div className="h-svh overflow-y-auto">
            <KnowledgeView />
          </div>
        )}
      </div>
    </div>
  );
}
