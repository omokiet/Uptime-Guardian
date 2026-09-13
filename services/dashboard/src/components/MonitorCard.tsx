import React from 'react';
import { ExternalLink, LineChart, Trash2 } from 'lucide-react';
import { Monitor } from '../types';
import { StatusDot } from './ui/StatusDot';

interface MonitorCardProps {
  monitor: Monitor;
  onSelect: (monitor: Monitor) => void;
  onDelete: (id: string) => void;
}

export const MonitorCard: React.FC<MonitorCardProps> = ({
  monitor,
  onSelect,
  onDelete,
}) => {
  return (
    <div className="p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-zinc-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/20 flex flex-col justify-between group">
      <div>
        {/* Top: Name & Status */}
        <div className="flex items-start justify-between gap-3 mb-2.5">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-white truncate group-hover:text-zinc-200 transition-colors">
              {monitor.name}
            </h3>
            <div className="flex items-center gap-1.5 mt-1 text-xs text-zinc-400 font-mono truncate">
              <a
                href={monitor.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline truncate"
              >
                {monitor.url}
              </a>
              <ExternalLink className="w-3 h-3 text-zinc-600 shrink-0 inline" />
            </div>
          </div>

          <StatusDot status={monitor.current_status} showText />
        </div>

        {/* Specs Metadata */}
        <div className="flex items-center gap-3 py-2 text-[11px] text-zinc-500 font-mono border-t border-brand-border/60 mt-3">
          <span>{monitor.method}</span>
          <span>•</span>
          <span>{monitor.interval_seconds}s interval</span>
          <span>•</span>
          <span>{monitor.timeout_seconds}s timeout</span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-3 mt-2 border-t border-brand-border/40">
        <span className="text-[11px] text-zinc-500 font-mono">
          Threshold: {monitor.consecutive_threshold} fails
        </span>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onSelect(monitor)}
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg bg-brand-subtle hover:bg-brand-border text-zinc-300 transition-all active:scale-95"
          >
            <LineChart className="w-3.5 h-3.5" />
            <span>Details</span>
          </button>
          <button
            onClick={() => {
              if (window.confirm(`Delete monitor "${monitor.name}"?`)) {
                onDelete(monitor.id);
              }
            }}
            className="p-1.5 rounded-lg text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-all active:scale-95"
            title="Delete monitor"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
