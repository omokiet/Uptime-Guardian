import axios from 'axios';
import { AuthResponse, CheckResult, CreateMonitorPayload, HourlySummary, Monitor, MonitorDetail, User } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('ug_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('ug_token');
      window.dispatchEvent(new Event('ug_auth_expired'));
    }
    return Promise.reject(error);
  }
);

// Auth API
export const apiLogin = async (email: string, password: string): Promise<AuthResponse> => {
  const { data } = await apiClient.post<AuthResponse>('/api/v1/auth/login', { email, password });
  return data;
};

export const apiRegister = async (email: string, password: string): Promise<User> => {
  const { data } = await apiClient.post<User>('/api/v1/auth/register', { email, password });
  return data;
};

export const apiGetMe = async (): Promise<User> => {
  const { data } = await apiClient.get<User>('/api/v1/auth/me');
  return data;
};

// Monitors API
export const apiGetMonitors = async (isActive?: boolean): Promise<Monitor[]> => {
  const params = isActive !== undefined ? { is_active: isActive } : {};
  const { data } = await apiClient.get<Monitor[]>('/api/v1/monitors', { params });
  return data;
};

export const apiGetMonitor = async (id: string): Promise<MonitorDetail> => {
  const { data } = await apiClient.get<MonitorDetail>(`/api/v1/monitors/${id}`);
  return data;
};

export const apiCreateMonitor = async (payload: CreateMonitorPayload): Promise<Monitor> => {
  const { data } = await apiClient.post<Monitor>('/api/v1/monitors', payload);
  return data;
};

export const apiUpdateMonitor = async (id: string, payload: Partial<CreateMonitorPayload>): Promise<Monitor> => {
  const { data } = await apiClient.put<Monitor>(`/api/v1/monitors/${id}`, payload);
  return data;
};

export const apiDeleteMonitor = async (id: string, hardDelete = false): Promise<void> => {
  await apiClient.delete(`/api/v1/monitors/${id}`, { params: { hard_delete: hardDelete } });
};

export const apiGetMonitorHistory = async (id: string, limit = 50): Promise<CheckResult[]> => {
  const { data } = await apiClient.get<CheckResult[]>(`/api/v1/monitors/${id}/history`, { params: { limit } });
  return data;
};

export const apiGetMonitorSummary = async (id: string, hours = 24): Promise<HourlySummary[]> => {
  const { data } = await apiClient.get<HourlySummary[]>(`/api/v1/monitors/${id}/summary`, { params: { hours } });
  return data;
};
