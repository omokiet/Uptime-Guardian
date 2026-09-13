import React, { useEffect, useState } from 'react';
import { ExternalLink, RefreshCw, X } from 'lucide-react';
import { apiGetMonitor, apiGetMonitorHistory } from '../api/client';
import { CheckResult, Monitor, MonitorDetail } from '../types';
import { LatencyChart } from './LatencyChart';
import { StatusDot } from './ui/StatusDot';

interface MonitorDetailModalProps {
  monitor: Monitor | null;
  onClose: () => void;
}

export const MonitorDetailModal: React.FC<MonitorDetailModalProps> = ({ monitor, onClose }) => {
  const [detail, setDetail] = useState<MonitorDetail | null>(null);
  const [history, setHistory] = useState<CheckResult[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchDetail = () => {
    if (!monitor) return;
    setLoading(true);
    Promise.all([
      apiGetMonitor(monitor.id),
      apiGetMonitorHistory(monitor.id, 20),
    ])
      .then(([detailData, historyData]) => {
        setDetail(detailData);
        setHistory(historyData);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchDetail();
  }, [monitor]);

  if (!monitor) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-2xl bg-brand-surface border border-brand-border rounded-xl p-6 shadow-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between pb-4 mb-4 border-b border-brand-border shrink-0">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-base font-semibold text-white">{monitor.name}</h2>
              <StatusDot status={monitor.current_status} showText />
            </div>
            <a
              href={monitor.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-zinc-400 font-mono mt-1 hover:underline inline-flex items-center gap-1"
            >
              <span>{monitor.url}</span>
              <ExternalLink className="w-3 h-3 text-zinc-500" />
            </a>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={fetchDetail}
              className="p-1.5 rounded-md text-zinc-400 hover:text-white hover:bg-brand-subtle transition-all active:scale-95"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-zinc-400 hover:text-white hover:bg-brand-subtle transition-all active:scale-95"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="overflow-y-auto space-y-5 pr-1 text-xs">
          {/* Summary Chips */}
          <div className="grid grid-cols-3 gap-2.5">
            <div className="p-3 bg-brand-bg border border-brand-border rounded-lg">
              <span className="text-[11px] text-zinc-400 font-mono">Interval</span>
              <p className="text-sm font-semibold font-mono text-white mt-1">
                {detail?.interval_seconds ?? monitor.interval_seconds}s
              </p>
            </div>

            <div className="p-3 bg-brand-bg border border-brand-border rounded-lg">
              <span className="text-[11px] text-zinc-400 font-mono">SSL Certificate</span>
              <p className="text-sm font-semibold font-mono text-white mt-1">
                {history[0]?.ssl_days_remaining !== null && history[0]?.ssl_days_remaining !== undefined
                  ? `${history[0].ssl_days_remaining} days left`
                  : '—'}
              </p>
            </div>

            <div className="p-3 bg-brand-bg border border-brand-border rounded-lg">
              <span className="text-[11px] text-zinc-400 font-mono">Method / Timeout</span>
              <p className="text-sm font-semibold font-mono text-white mt-1">
                {monitor.method} / {monitor.timeout_seconds}s
              </p>
            </div>
          </div>

          {/* Latency Section */}
          <div>
            <span className="block font-medium text-zinc-300 mb-2">Response Latency (RTT)</span>
            <LatencyChart checks={history} />
          </div>

          {/* Checks History Table */}
          <div>
            <span className="block font-medium text-zinc-300 mb-2">Recent Checks (Last 20)</span>
            {history.length === 0 ? (
              <div className="py-6 text-center text-zinc-500 font-mono border border-dashed border-brand-border rounded-lg">
                No check history available yet.
              </div>
            ) : (
              <div className="border border-brand-border rounded-lg overflow-hidden">
                <table className="w-full text-left font-mono text-xs">
                  <thead className="bg-brand-bg text-zinc-400 border-b border-brand-border">
                    <tr>
                      <th className="py-2 px-3">Timestamp</th>
                      <th className="py-2 px-3">HTTP Status</th>
                      <th className="py-2 px-3">Latency</th>
                      <th className="py-2 px-3 text-right">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-border/60">
                    {history.map((c) => (
                      <tr key={c.id} className="hover:bg-brand-subtle/50 transition-colors">
                        <td className="py-2 px-3 text-zinc-400">
                          {new Intl.DateTimeFormat('en-US', {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                            hour12: false,
                          }).format(new Date(c.created_at))}
                        </td>
                        <td className="py-2 px-3 text-white">
                          {c.status_code ?? 'Timeout'}
                        </td>
                        <td className="py-2 px-3 text-zinc-300">
                          {c.response_time_ms ? `${c.response_time_ms}ms` : '—'}
                        </td>
                        <td className="py-2 px-3 text-right">
                          <span
                            className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              c.is_success
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-rose-500/10 text-rose-400'
                            }`}
                          >
                            {c.is_success ? 'PASS' : 'FAIL'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
