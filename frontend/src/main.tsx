import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { showToast, getErrorMessage } from './lib/toast';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry on 401 - the interceptor handles logout immediately
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status === 401 || status === 403) return false;
        return failureCount < 1;
      },
    },
    mutations: {
      // Global fallback so a failed mutation is never silently swallowed — individual hooks
      // can still set their own onError to override this for cases needing custom handling.
      onError: (error) => {
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status === 401) return; // interceptor already handles logout + its own messaging
        showToast(getErrorMessage(error), 'error');
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
