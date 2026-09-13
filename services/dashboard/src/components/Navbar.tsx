import React from 'react';
import { LogIn, LogOut, Shield } from 'lucide-react';
import { User } from '../types';

interface NavbarProps {
  user: User | null;
  isConnected: boolean;
  onOpenAuth: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  isConnected,
  onOpenAuth,
  onLogout,
}) => {
  return (
    <header className="border-b border-brand-border bg-brand-surface/90 backdrop-blur-md sticky top-0 z-30 mb-8">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 transition-transform duration-200 hover:scale-105">
            <Shield className="w-4 h-4" />
          </div>
          <div className="flex items-center gap-2.5">
            <span className="font-semibold text-sm tracking-tight text-white">
              Uptime Guardian
            </span>
            <span className="text-zinc-600">/</span>
            <div className="flex items-center gap-1.5 text-xs text-zinc-400">
              <span className="relative flex h-2 w-2">
                {isConnected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
                )}
                <span
                  className={`relative inline-flex rounded-full h-2 w-2 ${
                    isConnected ? 'bg-emerald-500' : 'bg-rose-500'
                  }`}
                />
              </span>
              <span className="hidden sm:inline font-mono text-[11px]">
                {isConnected ? 'All systems operational' : 'API link offline'}
              </span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3">
          {user ? (
            <div className="flex items-center gap-3">
              <div className="text-right hidden sm:block">
                <p className="text-xs font-medium text-zinc-300 font-mono">{user.email}</p>
              </div>
              <button
                onClick={onLogout}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-brand-subtle border border-brand-border transition-all active:scale-95"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Log out</span>
              </button>
            </div>
          ) : (
            <button
              onClick={onOpenAuth}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium text-zinc-950 bg-white hover:bg-zinc-200 transition-all active:scale-95 shadow-sm"
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Sign in</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
