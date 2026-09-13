import React from 'react';

interface StatusDotProps {
  status: 'UP' | 'PENDING_DOWN' | 'DOWN' | 'UNKNOWN';
  showText?: boolean;
}

export const StatusDot: React.FC<StatusDotProps> = ({ status, showText = false }) => {
  const meta = {
    UP: {
      dot: 'bg-emerald-500',
      ping: 'bg-emerald-400',
      text: 'Operational',
      textColor: 'text-emerald-400',
      badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    },
    PENDING_DOWN: {
      dot: 'bg-amber-500',
      ping: 'bg-amber-400',
      text: 'Degraded',
      textColor: 'text-amber-400',
      badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    },
    DOWN: {
      dot: 'bg-rose-500',
      ping: 'bg-rose-400',
      text: 'Down',
      textColor: 'text-rose-400',
      badge: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    },
    UNKNOWN: {
      dot: 'bg-slate-500',
      ping: 'bg-slate-400',
      text: 'Unknown',
      textColor: 'text-slate-400',
      badge: 'bg-slate-800 text-slate-400 border-slate-700',
    },
  }[status] || {
    dot: 'bg-slate-500',
    ping: 'bg-slate-400',
    text: 'Unknown',
    textColor: 'text-slate-400',
    badge: 'bg-slate-800 text-slate-400 border-slate-700',
  };

  if (showText) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${meta.badge}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
        {meta.text}
      </span>
    );
  }

  return (
    <span className="relative flex h-2 w-2">
      {status === 'UP' && (
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${meta.ping}`}
        />
      )}
      <span className={`relative inline-flex rounded-full h-2 w-2 ${meta.dot}`} />
    </span>
  );
};
