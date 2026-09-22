import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Activity, FileSearch, Database, Sparkles, Layers, Terminal } from 'lucide-react';
import '../styles/admin-sidebar-nav.css';

const items = [
  { label: 'Monitor', title: 'Monitor (System Telemetry & Vitals)', icon: Activity },
  { label: 'Trace', title: 'Trace Inspector (Turn Execution & Latency Waterfall)', icon: FileSearch },
  { label: 'Memory & DB', title: 'Memory & Database (Schema Contracts & Evolution DB)', icon: Database },
  { label: 'Reasoning', title: 'System Reasoning (Overnight Learning & Self-Improvement)', icon: Sparkles },
  { label: 'Organs', title: 'Organs (Organ Introspection & Heartbeat Network)', icon: Layers },
  { label: 'Virtual CLI', title: 'Virtual CLI (Diagnostic Shell & Terminal)', icon: Terminal },
];

function isVisible(el: Element) {
  const node = el as HTMLElement;
  const style = window.getComputedStyle(node);
  const rect = node.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
}

export function AdminSidebarNav() {
  const [mount, setMount] = useState<HTMLElement | null>(null);
  const [tabActive, setTabActive] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [activeTitle, setActiveTitle] = useState('');

  useEffect(() => {
    const sync = () => {
      const actionButtons = items
        .map(item => Array.from(document.querySelectorAll('button[title]')).find(b => b.getAttribute('title') === item.title))
        .filter(Boolean) as Element[];
      setTabActive(actionButtons.some(isVisible));
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.getElementById('app-root') || document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
    window.addEventListener('resize', sync);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', sync);
    };
  }, []);

  useEffect(() => {
    if (!tabActive) {
      setMount(null);
      return;
    }
    const aside = document.querySelector('aside');
    if (!aside) return;

    const syncSidebar = () => {
      setCollapsed(aside.className.includes('md:w-16'));
      const active = Array.from(aside.querySelectorAll('button[title]')).find(button => {
        const title = button.getAttribute('title') || '';
        return items.some(item => item.title === title) && button.className.includes('bg-brand-600');
      });
      setActiveTitle(active?.getAttribute('title') || '');
    };
    syncSidebar();

    const host = document.createElement('div');
    host.className = 'jarvis-admin-sidebar-nav-host';
    aside.insertBefore(host, aside.firstElementChild);
    setMount(host);

    const observer = new MutationObserver(syncSidebar);
    observer.observe(aside, { subtree: true, attributes: true, attributeFilter: ['class'] });
    return () => {
      observer.disconnect();
      host.remove();
      setMount(null);
    };
  }, [tabActive]);

  const activate = (title: string) => {
    const button = Array.from(document.querySelectorAll('button[title]')).find(
      candidate => candidate.getAttribute('title') === title,
    ) as HTMLButtonElement | undefined;
    button?.click();
  };

  if (!mount || !tabActive || collapsed) return null;

  return createPortal(
    <div className="jarvis-admin-sidebar-nav" aria-label="JARVIS admin navigation">
      {items.map(({ label, title, icon: Icon }) => {
        const active = activeTitle === title;
        return (
          <button
            key={title}
            type="button"
            onClick={() => activate(title)}
            title={label}
            className={`jarvis-admin-sidebar-nav-item ${active ? 'is-active' : ''}`}
          >
            <Icon size={16} strokeWidth={1.9} />
            <span>{label}</span>
          </button>
        );
      })}
    </div>,
    mount,
  );
}
