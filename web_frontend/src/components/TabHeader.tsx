import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Radio } from 'lucide-react';

interface TabHeaderProps {
  icon: LucideIcon;
  category: string;
  title: string;
  subtitle?: string;
  controls?: React.ReactNode;
}

export const TabHeader: React.FC<TabHeaderProps> = ({
  icon: Icon,
  category,
  title,
  subtitle,
  controls,
}) => (
  <header
    className="trace-inspector-bar"
    style={{ position: 'static', top: 'auto', bottom: 'auto', inset: 'auto', zIndex: 'auto' }}
  >
    <div className="trace-inspector-brand">
      <div className="trace-inspector-icon trace-inspector-icon-live">
        <Icon size={19} />
        <span className="trace-inspector-pulse" />
      </div>
      <div className="trace-inspector-heading">
        <div className="trace-inspector-eyebrow"><Radio size={10} /> {category}</div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </div>

    {controls && <div className="trace-inspector-controls">{controls}</div>}
  </header>
);
