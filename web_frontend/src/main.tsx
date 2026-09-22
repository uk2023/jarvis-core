import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import { AppErrorBoundary } from './AppErrorBoundary.tsx';
import './index.css';
import './theme.css';

// GLOBAL SAFETY NET. AppErrorBoundary catches errors thrown DURING
// React's render/commit; this catches everything else that can still
// leave a blank page with no visible cause -- an error thrown from a
// setTimeout/event handler outside React's render cycle, or a rejected
// promise nobody awaited (a fetch in a useEffect with no .catch, for
// instance). Neither of those triggers a React error boundary at all.
// Logged to console AND, if the root has not painted anything yet,
// written directly into the page -- covering the exact "totally blank,
// nothing in devtools was open" case UK hit.
function showFatalError(title: string, detail: string): void {
  const root = document.getElementById('root');
  if (root && !root.hasChildNodes()) {
    root.innerHTML = `
      <div style="min-height:100vh;padding:24px;font-family:ui-monospace,monospace;
                  background:#0b0f1a;color:#e2e8f0;">
        <h1 style="font-size:16px;">⚠ ${title}</h1>
        <pre style="background:#141b2d;border:1px solid #2a3550;border-radius:10px;
                    padding:14px;font-size:12px;white-space:pre-wrap;color:#fca5a5;">${detail}</pre>
      </div>`;
  }
}

window.addEventListener('error', (e) => {
  console.error('[JARVIS fatal]', e.error || e.message);
  showFatalError('JARVIS frontend error', String(e.error?.stack || e.message));
});

window.addEventListener('unhandledrejection', (e) => {
  console.error('[JARVIS unhandled promise rejection]', e.reason);
  showFatalError('JARVIS unhandled promise rejection', String(e.reason?.stack || e.reason));
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
