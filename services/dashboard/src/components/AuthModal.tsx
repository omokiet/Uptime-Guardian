import React, { useState } from 'react';
import { AlertCircle, X } from 'lucide-react';
import { apiLogin, apiRegister } from '../api/client';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);

    try {
      if (isRegister) {
        await apiRegister(email, password);
      }
      const data = await apiLogin(email, password);
      localStorage.setItem('ug_token', data.access_token);
      onSuccess();
      onClose();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const axErr = err as { response?: { data?: { detail?: string } } };
        setErrorMsg(axErr.response?.data?.detail || 'Authentication failed.');
      } else {
        setErrorMsg('Server connection failed.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-sm bg-brand-surface border border-brand-border rounded-xl p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-3 mb-4 border-b border-brand-border">
          <div className="flex gap-4 text-sm font-medium">
            <button
              type="button"
              onClick={() => {
                setIsRegister(false);
                setErrorMsg(null);
              }}
              className={`pb-1 transition-colors ${
                !isRegister
                  ? 'text-white border-b-2 border-white'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => {
                setIsRegister(true);
                setErrorMsg(null);
              }}
              className={`pb-1 transition-colors ${
                isRegister
                  ? 'text-white border-b-2 border-white'
                  : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              Sign Up
            </button>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-white hover:bg-brand-subtle transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {errorMsg && (
          <div className="flex items-center gap-2 p-2.5 mb-4 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
          <div>
            <label className="block font-medium text-zinc-300 mb-1">Email address</label>
            <input
              type="email"
              required
              placeholder="admin@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white text-sm transition-colors"
            />
          </div>

          <div>
            <label className="block font-medium text-zinc-300 mb-1">Password</label>
            <input
              type="password"
              required
              minLength={6}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-brand-bg border border-brand-border focus:border-zinc-500 focus:outline-none rounded-lg text-white text-sm transition-colors"
            />
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2 px-4 rounded-lg text-xs font-medium text-zinc-950 bg-white hover:bg-zinc-200 transition-all active:scale-95 disabled:opacity-50 shadow-sm"
            >
              {loading
                ? 'Processing...'
                : isRegister
                ? 'Create Account'
                : 'Sign In'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
