import { useEffect, useRef, useState, useCallback } from 'react';
import { Monitor } from '../types';

export interface TelemetryCheckResultData {
  monitor_id: string;
  region_id: string;
  status_code: number | null;
  response_time_ms: number | null;
  is_success: boolean;
  error_message: string | null;
  ssl_days_remaining: number | null;
}

export interface TelemetryStatusChangeData {
  monitor_id: string;
  previous_status: Monitor['current_status'];
  new_status: Monitor['current_status'];
  reason: string;
}

export type TelemetryEvent =
  | { event: 'connected'; user_id: string }
  | { event: 'check_result'; timestamp: string; data: TelemetryCheckResultData }
  | { event: 'status_change'; timestamp: string; data: TelemetryStatusChangeData }
  | { event: 'ping' }
  | { event: 'pong'; timestamp: string };

interface UseWebSocketTelemetryOptions {
  onCheckResult?: (data: TelemetryCheckResultData) => void;
  onStatusChange?: (data: TelemetryStatusChangeData) => void;
}

const getWebSocketUrl = (token: string): string => {
  const envApiUrl = import.meta.env.VITE_API_URL;
  if (envApiUrl) {
    const wsBase = envApiUrl.replace(/^http(s?):/, 'ws$1:');
    return `${wsBase}/ws/telemetry?token=${encodeURIComponent(token)}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/telemetry?token=${encodeURIComponent(token)}`;
};

export const useWebSocketTelemetry = (options: UseWebSocketTelemetryOptions = {}) => {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const backoffDelayRef = useRef<number>(1000);
  const isUnmountedRef = useRef<boolean>(false);

  const { onCheckResult, onStatusChange } = options;

  const connect = useCallback(() => {
    if (isUnmountedRef.current) return;

    const token = localStorage.getItem('ug_token');
    if (!token) {
      setIsConnected(false);
      return;
    }

    try {
      const url = getWebSocketUrl(token);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isUnmountedRef.current) {
          ws.close();
          return;
        }
        setIsConnected(true);
        backoffDelayRef.current = 1000;
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as TelemetryEvent;
          if (payload.event === 'check_result' && onCheckResult) {
            onCheckResult(payload.data);
          } else if (payload.event === 'status_change' && onStatusChange) {
            onStatusChange(payload.data);
          } else if (payload.event === 'ping') {
            ws.send(JSON.stringify({ action: 'ping' }));
          }
        } catch {
          // Ignore unparseable frames
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        if (!isUnmountedRef.current) {
          // Schedule exponential backoff reconnect
          const delay = backoffDelayRef.current;
          backoffDelayRef.current = Math.min(delay * 2, 10000);
          reconnectTimeoutRef.current = window.setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      setIsConnected(false);
    }
  }, [onCheckResult, onStatusChange]);

  useEffect(() => {
    isUnmountedRef.current = false;
    connect();

    return () => {
      isUnmountedRef.current = true;
      if (reconnectTimeoutRef.current !== null) {
        window.clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { isConnected };
};
