import { createContext, useContext } from 'react';

export interface Toast {
  id: number;
  tone: 'error' | 'success' | 'info';
  message: string;
  requestId?: string | null;
}

export interface ToastApi {
  show: (toast: Omit<Toast, 'id'>) => void;
}

export const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error('useToast must be used inside <ToastProvider>');
  return api;
}
