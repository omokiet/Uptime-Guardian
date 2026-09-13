import React from 'react';
import { Monitor } from '../types';

interface StatsOverviewProps {
  monitors: Monitor[];
}

export const StatsOverview: React.FC<StatsOverviewProps> = ({ monitors }) => {
  const total = monitors.length;
  const up = monitors.filter((m) => m.current_status === 'UP').length;
  const down = monitors.filter((m) => m.current_status === 'DOWN').length;
  const pending = monitors.filter((m) => m.current_status === 'PENDING_DOWN').length;

  const uptimePercentage = total > 0 ? ((up / total) * 100).toFixed(1) : '100.0';

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-8">
      {/* 1. Uptime */}
      <div className="group p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-zinc-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20">
        <span className="text-xs font-medium text-zinc-400">System Uptime</span>
        <div className="mt-2.5 flex items-baseline gap-1.5">
          <span className="text-2xl font-semibold tracking-tight text-white font-mono">
            {uptimePercentage}%
          </span>
        </div>
        <p className="mt-1 text-[11px] text-zinc-500 font-mono">SLO Target 99.9%</p>
      </div>

      {/* 2. Operational */}
      <div className="group p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-zinc-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20">
        <span className="text-xs font-medium text-zinc-400">Operational</span>
        <div className="mt-2.5 flex items-baseline gap-1.5">
          <span className="text-2xl font-semibold tracking-tight text-emerald-400 font-mono">
            {up}
          </span>
          <span className="text-xs text-zinc-500 font-mono">/ {total} monitors</span>
        </div>
        <p className="mt-1 text-[11px] text-zinc-500 font-mono">Healthy endpoints</p>
      </div>

      {/* 3. Incidents */}
      <div className="group p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-zinc-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20">
        <span className="text-xs font-medium text-zinc-400">Active Incidents</span>
        <div className="mt-2.5 flex items-baseline gap-1.5">
          <span
            className={`text-2xl font-semibold tracking-tight font-mono ${
              down > 0 ? 'text-rose-400' : 'text-white'
            }`}
          >
            {down}
          </span>
          <span className="text-xs text-zinc-500 font-mono">down</span>
        </div>
        <p className="mt-1 text-[11px] text-zinc-500 font-mono">
          {down > 0 ? 'Requires attention' : 'All services normal'}
        </p>
      </div>

      {/* 4. Degraded / Retrying */}
      <div className="group p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-zinc-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20">
        <span className="text-xs font-medium text-zinc-400">Pending Retry</span>
        <div className="mt-2.5 flex items-baseline gap-1.5">
          <span
            className={`text-2xl font-semibold tracking-tight font-mono ${
              pending > 0 ? 'text-amber-400' : 'text-white'
            }`}
          >
            {pending}
          </span>
          <span className="text-xs text-zinc-500 font-mono">verifying</span>
        </div>
        <p className="mt-1 text-[11px] text-zinc-500 font-mono">Consecutive threshold</p>
      </div>
    </div>
  );
};
