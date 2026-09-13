import React, { useState } from 'react';
import { AlertCircle, X } from 'lucide-react';
import { CreateMonitorPayload } from '../types';

interface AddMonitorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateMonitorPayload) => Promise<void>;
}

export const AddMonitorModal: React.FC<AddMonitorModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
}) => {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [method, setMethod] = useState('GET');
  const [intervalSeconds, setIntervalSeconds] = useState(60);
  const [timeoutSeconds, setTimeoutSeconds] = useState(10);
  const [expectedStatusCode, setExpectedStatusCode] = useState(200);
  const [consecutiveThreshold, setConsecutiveThreshold] = useState(3);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const applyPreset = (pName: string, pUrl: string, pInterval = 60) => {
    setName(pName);
    setUrl(pUrl);
    setIntervalSeconds(pInterval);
    setMethod('GET');
    setExpectedStatusCode(200);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);

    try {
      await onSubmit({
        name,
        url,
        method,
        interval_seconds: Number(intervalSeconds),
        timeout_seconds: Number(timeoutSeconds),
        expected_status_code: Number(expectedStatusCode),
        consecutive_threshold: Number(consecutiveThreshold),
      });
      onClose();
      setName('');
      setUrl('');
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axErr = err as { response?: { data?: { detail?: string } } };
        setErrorMsg(axErr.response?.data?.detail || 'Failed to create monitor.');
      } else {
        setErrorMsg('Server connection failed.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-lg bg-brand-surface border border-brand-border rounded-xl p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-brand-border">
          <h2 className="text-base font-semibold text-white">New Monitor</h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-brand-subtle transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Presets */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <span className="text-xs text-zinc-400">Presets:</span>
          <button
            type="button"
            onClick={() => applyPreset('Google', 'https://google.com', 60)}
            className="px-2.5 py-1 text-xs rounded-md bg-brand-subtle hover:bg-brand-border text-zinc-300 transition-all active:scale-95"
          >
            Google (60s)
          </button>
          <button
            type="button"
            onClick={() => applyPreset('Cloudflare', 'https://1.1.1.1', 30)}
            className="px-2.5 py-1 text-xs rounded-md bg-brand-subtle hover:bg-brand-border text-zinc-300 transition-all active:scale-95"
          >
            Cloudflare (30s)
          </button>
          <button
            type="button"
            onClick={() => applyPreset('GitHub API', 'https://api.github.com', 60)}
            className="px-2.5 py-1 text-xs rounded-md bg-brand-subtle hover:bg-brand-border text-zinc-300 transition-all active:scale-95"
          >
            GitHub (60s)
          </button>
        </div>

        {errorMsg && (
          <div className="flex items-center gap-2 p-3 mb-4 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block font-medium text-zinc-300 mb-1.5">Monitor Name</label>
            <input
              type="text"
              required
              placeholder="e.g. Production API"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white text-sm transition-colors"
            />
          </div>

          <div>
            <label className="block font-medium text-zinc-300 mb-1.5">Target URL</label>
            <input
              type="url"
              required
              placeholder="https://example.com/health"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white text-sm font-mono transition-colors"
            />
            <p className="mt-1 text-[11px] text-zinc-500 font-mono">
              Private and internal loopback IP addresses are blocked (Anti-SSRF).
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block font-medium text-zinc-300 mb-1.5">HTTP Method</label>
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white"
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="HEAD">HEAD</option>
              </select>
            </div>

            <div>
              <label className="block font-medium text-zinc-300 mb-1.5">Check Interval</label>
              <select
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Number(e.target.value))}
                className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white font-mono"
              >
                <option value={30}>Every 30 seconds</option>
                <option value={60}>Every 60 seconds (1 min)</option>
                <option value={300}>Every 300 seconds (5 min)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block font-medium text-zinc-400 mb-1.5 font-mono">Timeout (s)</label>
              <input
                type="number"
                min={1}
                max={60}
                value={timeoutSeconds}
                onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white font-mono"
              />
            </div>

            <div>
              <label className="block font-medium text-zinc-400 mb-1.5 font-mono">Expected Code</label>
              <input
                type="number"
                min={100}
                max={599}
                value={expectedStatusCode}
                onChange={(e) => setExpectedStatusCode(Number(e.target.value))}
                className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white font-mono"
              />
            </div>

            <div>
              <label className="block font-medium text-zinc-400 mb-1.5 font-mono">Fail Threshold</label>
              <input
                type="number"
                min={1}
                max={10}
                value={consecutiveThreshold}
                onChange={(e) => setConsecutiveThreshold(Number(e.target.value))}
                className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white font-mono"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2.5 pt-4 border-t border-brand-border">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-brand-subtle transition-all active:scale-95"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-1.5 rounded-lg text-zinc-950 font-medium bg-white hover:bg-zinc-200 transition-all active:scale-95 disabled:opacity-50 shadow-sm"
            >
              {loading ? 'Creating...' : 'Create monitor'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
