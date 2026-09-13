import React from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { CheckResult } from '../types';

interface LatencyChartProps {
  checks: CheckResult[];
}

export const LatencyChart: React.FC<LatencyChartProps> = ({ checks }) => {
  if (!checks || checks.length === 0) {
    return (
      <div className="h-44 flex items-center justify-center border border-dashed border-brand-border rounded-lg bg-brand-bg/50 text-xs text-zinc-500 font-mono">
        Chưa có dữ liệu kiểm tra gần đây
      </div>
    );
  }

  const data = [...checks]
    .reverse()
    .map((c) => ({
      time: new Intl.DateTimeFormat('vi-VN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(c.created_at)),
      latency: c.response_time_ms !== null ? Math.min(c.response_time_ms, 5000) : 0,
      statusCode: c.status_code,
      isSuccess: c.is_success,
    }));

  return (
    <div className="w-full h-52 bg-brand-bg/40 border border-brand-border rounded-xl p-4">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="latencyGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10B981" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#10B981" stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#232631" vertical={false} />
          <XAxis
            dataKey="time"
            stroke="#52525b"
            tick={{ fontSize: 10, fontFamily: 'JetBrains Mono' }}
            tickLine={false}
          />
          <YAxis
            stroke="#52525b"
            tick={{ fontSize: 10, fontFamily: 'JetBrains Mono' }}
            tickLine={false}
            unit="ms"
          />
          <Tooltip
            content={({ active, payload }) => {
              if (active && payload && payload.length) {
                const item = payload[0].payload;
                return (
                  <div className="bg-brand-surface border border-brand-border rounded-lg p-2.5 shadow-lg text-xs font-mono">
                    <p className="text-zinc-400 mb-1">{item.time}</p>
                    <p className="text-emerald-400 font-medium">
                      Độ trễ: <span className="text-white">{item.latency}ms</span>
                    </p>
                    <p className="text-zinc-300 mt-0.5">
                      Status: {item.statusCode ?? 'TIMEOUT'}
                    </p>
                  </div>
                );
              }
              return null;
            }}
          />
          <Area
            type="monotone"
            dataKey="latency"
            stroke="#10B981"
            strokeWidth={1.5}
            fillOpacity={1}
            fill="url(#latencyGradient)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};
