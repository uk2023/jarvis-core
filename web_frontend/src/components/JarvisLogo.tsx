import React from 'react';

interface JarvisLogoProps {
  /** Pixel size of the square logo mark. Defaults to 40. */
  size?: number;
  /** Show the slow ambient pulse/rotation. Default true. Set false for tiny/static contexts. */
  animated?: boolean;
  className?: string;
}

/**
 * A single, reusable animated JARVIS mark -- one calm rotating core ring,
 * one orbiting particle, one soft pulse. Deliberately restrained (no
 * neon glassmorphism stack) so it reads as "futuristic core", not
 * "loading spinner". Pure SVG + CSS, fully scalable -- safe to drop at
 * any size, including inside a small floating/always-on-top window.
 */
export function JarvisLogo({ size = 40, animated = true, className = '' }: JarvisLogoProps) {
  return (
    <div
      className={`relative shrink-0 ${className}`}
      style={{ width: size, height: size }}
      aria-label="JARVIS"
      role="img"
    >
      <svg
        viewBox="0 0 100 100"
        width={size}
        height={size}
        className={animated ? 'jarvis-logo-spin' : ''}
        style={{ overflow: 'visible' }}
      >
        <defs>
          <radialGradient id="jarvisCoreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--jarvis-accent-strong, #7ba3f2)" stopOpacity="0.9" />
            <stop offset="100%" stopColor="var(--jarvis-accent, #5b8def)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="jarvisRingGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--jarvis-accent-strong, #7ba3f2)" />
            <stop offset="100%" stopColor="var(--jarvis-accent, #5b8def)" />
          </linearGradient>
        </defs>

        {/* Soft ambient glow behind everything */}
        <circle cx="50" cy="50" r="46" fill="url(#jarvisCoreGlow)" opacity="0.35" className={animated ? 'jarvis-logo-breathe' : ''} />

        {/* Outer ring -- broken arc, gives a "HUD" read rather than a plain circle */}
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="url(#jarvisRingGradient)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray="184 264"
          opacity="0.9"
        />

        {/* Inner ring, counter-rotating for parallax depth */}
        <circle
          cx="50"
          cy="50"
          r="30"
          fill="none"
          stroke="var(--jarvis-accent, #5b8def)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray="12 10"
          opacity="0.5"
          className={animated ? 'jarvis-logo-spin-reverse' : ''}
        />

        {/* Orbiting particle */}
        <g className={animated ? 'jarvis-logo-orbit' : ''}>
          <circle cx="50" cy="8" r="3.2" fill="var(--jarvis-accent-strong, #7ba3f2)" />
        </g>

        {/* Steady core */}
        <circle cx="50" cy="50" r="10" fill="var(--jarvis-accent, #5b8def)" className={animated ? 'jarvis-logo-pulse' : ''} />
        <circle cx="50" cy="50" r="4" fill="#ffffff" />
      </svg>

      <style>{`
        .jarvis-logo-spin { animation: jarvis-spin 14s linear infinite; }
        .jarvis-logo-spin-reverse { transform-origin: 50px 50px; animation: jarvis-spin-reverse 9s linear infinite; }
        .jarvis-logo-orbit { transform-origin: 50px 50px; animation: jarvis-spin 5s linear infinite; }
        .jarvis-logo-pulse { animation: jarvis-pulse 2.4s ease-in-out infinite; }
        .jarvis-logo-breathe { animation: jarvis-breathe 3.6s ease-in-out infinite; }

        @keyframes jarvis-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes jarvis-spin-reverse {
          from { transform: rotate(360deg); }
          to { transform: rotate(0deg); }
        }
        @keyframes jarvis-pulse {
          0%, 100% { r: 10; opacity: 1; }
          50% { r: 11.5; opacity: 0.85; }
        }
        @keyframes jarvis-breathe {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 0.5; }
        }

        @media (prefers-reduced-motion: reduce) {
          .jarvis-logo-spin, .jarvis-logo-spin-reverse, .jarvis-logo-orbit, .jarvis-logo-pulse, .jarvis-logo-breathe {
            animation: none;
          }
        }
      `}</style>
    </div>
  );
}
