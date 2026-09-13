import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  Plus,
  RefreshCw,
  Search,
  Shield,
} from 'lucide-react';
import {
  apiCreateMonitor,
  apiDeleteMonitor,
  apiGetMe,
  apiGetMonitors,
} from './api/client';
import { AddMonitorModal } from './components/AddMonitorModal';
import { AuthModal } from './components/AuthModal';
import { MonitorCard } from './components/MonitorCard';
import { MonitorDetailModal } from './components/MonitorDetailModal';
import { Navbar } from './components/Navbar';
import { StatsOverview } from './components/StatsOverview';
import { CreateMonitorPayload, Monitor, User } from './types';

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(null);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedMonitor, setSelectedMonitor] = useState<Monitor | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'UP' | 'DOWN'>('ALL');

  const fetchMonitors = useCallback(async () => {
    try {
      const data = await apiGetMonitors();
      setMonitors(data);
      setConnectionError(null);
    } catch {
      setConnectionError('Unable to connect to API Gateway. (Showing cached data)');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchUserData = useCallback(async () => {
    const token = localStorage.getItem('ug_token');
    if (!token) {
      setUser(null);
      await fetchMonitors();
      return;
    }

    try {
      const userData = await apiGetMe();
      setUser(userData);
      await fetchMonitors();
    } catch {
      localStorage.removeItem('ug_token');
      setUser(null);
      await fetchMonitors();
    }
  }, [fetchMonitors]);

  useEffect(() => {
    const handleAuthExpired = () => {
      setUser(null);
      setIsAuthOpen(true);
    };
    window.addEventListener('ug_auth_expired', handleAuthExpired);
    return () => window.removeEventListener('ug_auth_expired', handleAuthExpired);
  }, []);

  useEffect(() => {
    fetchUserData();
  }, [fetchUserData]);

  useEffect(() => {
    const interval = setInterval(() => {
      if (!isAddOpen && !isAuthOpen) {
        fetchMonitors();
      }
    }, 15000);
    return () => clearInterval(interval);
  }, [fetchMonitors, isAddOpen, isAuthOpen]);

  const handleLogout = () => {
    localStorage.removeItem('ug_token');
    setUser(null);
    fetchMonitors();
  };

  const handleCreateMonitor = async (payload: CreateMonitorPayload) => {
    const newMon = await apiCreateMonitor(payload);
    setMonitors((prev) => [newMon, ...prev]);
  };

  const handleDeleteMonitor = async (id: string) => {
    try {
      await apiDeleteMonitor(id, true);
      setMonitors((prev) => prev.filter((m) => m.id !== id));
      if (selectedMonitor?.id === id) {
        setSelectedMonitor(null);
      }
    } catch {
      alert('Unable to delete monitor.');
    }
  };

  const filteredMonitors = monitors.filter((m) => {
    const matchesSearch =
      m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      m.url.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'ALL' || m.current_status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="min-h-screen bg-brand-bg text-zinc-100 pb-20">
      <Navbar
        user={user}
        isConnected={!connectionError}
        onOpenAuth={() => setIsAuthOpen(true)}
        onLogout={handleLogout}
      />

      <main className="max-w-6xl mx-auto px-4 sm:px-6">
        {/* Offline notification banner */}
        {connectionError && (
          <div className="flex items-center justify-between p-3.5 mb-6 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
            <div className="flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{connectionError}</span>
            </div>
            <button
              onClick={() => {
                setLoading(true);
                fetchMonitors();
              }}
              className="px-3 py-1 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 transition-all font-medium active:scale-95"
            >
              Retry
            </button>
          </div>
        )}

        {/* System Summary */}
        <StatsOverview monitors={monitors} />

        {/* Unified Toolbar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div className="flex items-center gap-2.5 flex-1 max-w-lg">
            {/* Search Input */}
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search monitors by name or URL..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full h-9 pl-9 pr-3.5 bg-brand-surface border border-brand-border rounded-lg text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500 transition-colors"
              />
            </div>

            {/* Filter Tabs (Uniform height h-9, All / Up / Down) */}
            <div className="flex items-center h-9 bg-brand-surface p-1 rounded-lg border border-brand-border text-xs">
              {(
                [
                  { key: 'ALL', label: 'All' },
                  { key: 'UP', label: 'Up' },
                  { key: 'DOWN', label: 'Down' },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setStatusFilter(tab.key)}
                  className={`h-7 px-3 rounded-md font-medium whitespace-nowrap transition-all duration-150 active:scale-95 ${
                    statusFilter === tab.key
                      ? 'bg-brand-subtle text-white shadow-sm'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {/* Action Buttons (Uniform height h-9) */}
          <div className="flex items-center gap-2">
            <button
              onClick={fetchMonitors}
              className="h-9 w-9 flex items-center justify-center rounded-lg bg-brand-surface hover:bg-brand-subtle text-zinc-400 hover:text-white border border-brand-border transition-all active:scale-95"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>

            <button
              onClick={() => {
                if (!user) {
                  setIsAuthOpen(true);
                } else {
                  setIsAddOpen(true);
                }
              }}
              className="h-9 flex items-center gap-1.5 px-3.5 rounded-lg text-xs font-medium text-zinc-950 bg-white hover:bg-zinc-200 transition-all active:scale-95 shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>Add monitor</span>
            </button>
          </div>
        </div>

        {/* Content Area */}
        {loading && monitors.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 border border-brand-border rounded-xl bg-brand-surface/40">
            <RefreshCw className="w-5 h-5 text-zinc-400 animate-spin mb-2" />
            <p className="text-xs text-zinc-500 font-mono">Loading monitors...</p>
          </div>
        ) : filteredMonitors.length === 0 ? (
          /* Empty State */
          <div className="flex flex-col items-center justify-center py-16 px-4 border border-dashed border-brand-border rounded-xl bg-brand-surface/20 text-center transition-all">
            <div className="w-12 h-12 rounded-full bg-brand-subtle border border-brand-border flex items-center justify-center text-zinc-400 mb-3.5 transition-transform hover:scale-105">
              <Shield className="w-6 h-6 text-zinc-400" />
            </div>
            <h3 className="text-sm font-semibold text-white">
              {searchQuery ? 'No matching monitors found' : 'No monitors created yet'}
            </h3>
            <p className="text-xs text-zinc-400 max-w-sm mt-1 mb-5 leading-relaxed">
              {searchQuery
                ? 'Try adjusting your search query or filter criteria.'
                : 'Track uptime, response latency, and SSL certificate expiration for your websites and APIs.'}
            </p>
            <button
              onClick={() => {
                if (!user) {
                  setIsAuthOpen(true);
                } else {
                  setIsAddOpen(true);
                }
              }}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium text-zinc-950 bg-white hover:bg-zinc-200 transition-all active:scale-95 shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>Create first monitor</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {filteredMonitors.map((monitor) => (
              <MonitorCard
                key={monitor.id}
                monitor={monitor}
                onSelect={setSelectedMonitor}
                onDelete={handleDeleteMonitor}
              />
            ))}
          </div>
        )}
      </main>

      <AddMonitorModal
        isOpen={isAddOpen}
        onClose={() => setIsAddOpen(false)}
        onSubmit={handleCreateMonitor}
      />

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onSuccess={fetchUserData}
      />

      <MonitorDetailModal
        monitor={selectedMonitor}
        onClose={() => setSelectedMonitor(null)}
      />
    </div>
  );
};

export default App;
