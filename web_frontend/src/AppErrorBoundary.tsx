import { Component, type ErrorInfo, type ReactNode } from 'react';

/**
 * VISIBLE CRASHES, NOT BLANK PAGES.
 *
 * UK reported a black/blank page at localhost:5173 with no error
 * overlay at all. Exhaustive checking this round found the code itself
 * sound -- a full esbuild bundle of the entire app, resolving every
 * local import against its actual exports, completed with zero errors
 * -- which points at a stale cached build rather than a new bug. But
 * that investigation surfaced a real, separate problem worth fixing on
 * its own: if a React render DOES throw at runtime (from data shaped
 * unexpectedly, a browser API missing on some device, anything Vite's
 * build-time overlay cannot catch because the code is syntactically
 * fine), React unmounts the whole tree and the page goes silently
 * blank. Nothing tells UK what broke, and nothing tells ME either --
 * he can only screenshot an empty screen.
 *
 * This boundary catches exactly that class of failure and renders the
 * actual error message and stack instead of nothing. It does not fix
 * the underlying bug when one exists; it makes the underlying bug
 * VISIBLE, which is the prerequisite for ever fixing it from a
 * screenshot instead of guessing.
 */

interface State {
  error: Error | null;
  info: ErrorInfo | null;
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ error, info });
    // Also to the console, in case devtools ARE open -- this component
    // exists for when they are not, but should not make that case
    // worse.
    console.error('[JARVIS crash]', error, info.componentStack);
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          padding: 24,
          fontFamily: 'ui-monospace, monospace',
          background: '#0b0f1a',
          color: '#e2e8f0',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>⚠</span>
          <h1 style={{ fontSize: 16, margin: 0, fontWeight: 700 }}>JARVIS frontend crashed</h1>
        </div>

        <p style={{ margin: 0, fontSize: 13, opacity: 0.8, maxWidth: 640 }}>
          Yeh screen isliye dikh rahi hai taaki blank page ki jagah asli error dikhe.
          Neeche ka message aur stack copy karke bhejo -- isse asli jagah pakadna
          seconds mein ho jaata hai, screenshot se guess karne ke bajaye.
        </p>

        <pre
          style={{
            background: '#141b2d',
            border: '1px solid #2a3550',
            borderRadius: 10,
            padding: 14,
            fontSize: 12,
            lineHeight: 1.5,
            overflow: 'auto',
            maxHeight: '40vh',
            color: '#fca5a5',
          }}
        >
          {error.name}: {error.message}
          {'\n\n'}
          {error.stack}
        </pre>

        {info?.componentStack && (
          <details style={{ fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', opacity: 0.7 }}>Component stack</summary>
            <pre
              style={{
                background: '#141b2d',
                border: '1px solid #2a3550',
                borderRadius: 10,
                padding: 14,
                marginTop: 8,
                overflow: 'auto',
                maxHeight: '30vh',
              }}
            >
              {info.componentStack}
            </pre>
          </details>
        )}

        <button
          onClick={() => window.location.reload()}
          style={{
            alignSelf: 'flex-start',
            padding: '8px 16px',
            borderRadius: 10,
            border: '1px solid #4f46e5',
            background: '#4f46e520',
            color: '#a5b4fc',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
