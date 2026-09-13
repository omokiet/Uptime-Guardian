export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface Monitor {
  id: string;
  user_id: string;
  name: string;
  url: string;
  method: string;
  interval_seconds: number;
  timeout_seconds: number;
  expected_status_code: number;
  consecutive_threshold: number;
  current_status: 'UP' | 'PENDING_DOWN' | 'DOWN' | 'UNKNOWN';
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CheckResult {
  id: number;
  monitor_id: string;
  job_id: string;
  status_code: number | null;
  response_time_ms: number | null;
  is_success: boolean;
  error_message: string | null;
  ssl_days_remaining: number | null;
  created_at: string;
}

export interface HourlySummary {
  id: number;
  monitor_id: string;
  hour_timestamp: string;
  total_checks: number;
  success_checks: number;
  avg_response_time_ms: number;
  uptime_percentage: number;
}

export interface MonitorDetail extends Monitor {
  recent_checks: CheckResult[];
  uptime_percentage_24h?: number;
  avg_response_time_24h?: number;
}

export interface CreateMonitorPayload {
  name: string;
  url: string;
  method?: string;
  interval_seconds?: number;
  timeout_seconds?: number;
  expected_status_code?: number;
  consecutive_threshold?: number;
  is_active?: boolean;
}
