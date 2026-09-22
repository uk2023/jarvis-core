const ITEMS = [
  ['Monitor (System Telemetry & Vitals)', 'Monitor', '◉'],
  ['Trace Inspector (Turn Execution & Latency Waterfall)', 'Trace', '⌁'],
  ['Memory & Database (Schema Contracts & Evolution DB)', 'Memory & DB', '▣'],
  ['System Reasoning (Overnight Learning & Self-Improvement)', 'Reasoning', '✦'],
  ['Organs (Organ Introspection & Heartbeat Network)', 'Organs', '◇'],
  ['Virtual CLI (Diagnostic Shell & Terminal)', 'Virtual CLI', '>_'],
] as const;

const STYLE_ID = 'jarvis-inspection-v2-styles';
const HOST = 'jarvis-inspection-v2';
const HIDDEN = 'jarvis-inspection-v2-hidden';

function styles() {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement('style');
  s.id = STYLE_ID;
  s.textContent = `
    .${HIDDEN}{display:none!important;visibility:hidden!important;}
    .${HOST}{width:100%;margin-top:8px;position:relative;z-index:20;}
    .${HOST} .inspection-trigger{width:100%;display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border:1px solid var(--jarvis-border,#263044);border-radius:11px;background:var(--jarvis-surface,#101522);color:var(--jarvis-text,#e5e7eb);font-size:11px;font-weight:700;cursor:pointer;}
    .${HOST} .inspection-left{display:flex;align-items:center;gap:7px;}
    .${HOST} .inspection-icon{width:18px;height:18px;display:grid;place-items:center;border-radius:6px;background:color-mix(in srgb,var(--jarvis-accent,#3b82f6) 14%,transparent);color:var(--jarvis-accent,#3b82f6);}
    .${HOST} .inspection-chevron{transition:transform .22s ease;color:var(--jarvis-text-muted,#94a3b8);}
    .${HOST}.open .inspection-chevron{transform:rotate(90deg);}
    .${HOST} .inspection-clip{display:grid;grid-template-rows:0fr;transition:grid-template-rows .28s cubic-bezier(.22,1,.36,1);}
    .${HOST}.open .inspection-clip{grid-template-rows:1fr;}
    .${HOST} .inspection-panel{min-height:0;overflow:hidden;}
    .${HOST} .inspection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;padding:7px 0 1px;}
    .${HOST} .inspection-item{height:44px;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:3px 2px;border:1px solid var(--jarvis-border,#263044);border-radius:10px;background:var(--jarvis-surface,#101522);color:var(--jarvis-text-muted,#94a3b8);cursor:pointer;}
    .${HOST} .inspection-item:hover{background:var(--jarvis-surface-raised,#171d2b);color:var(--jarvis-text,#e5e7eb);}
    .${HOST} .inspection-item.active{background:var(--jarvis-accent,#3b82f6);border-color:var(--jarvis-accent,#3b82f6);color:#fff;}
    .${HOST} .inspection-item-icon{font-size:13px;font-weight:800;line-height:1;}
    .${HOST} .inspection-item-label{font-size:7.5px;font-weight:700;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}
  `;
  document.head.appendChild(s);
}

function source(title: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll('button[title]')).find(b => b.getAttribute('title') === title) as HTMLButtonElement | null;
}

function hideLegacy() {
  ITEMS.forEach(([title]) => {
    const b = source(title);
    if (!b) return;
    b.classList.add(HIDDEN);
    let p = b.parentElement as HTMLElement | null;
    for (let i = 0; p && i < 3; i++) {
      if (ITEMS.filter(([t]) => p!.querySelector(`button[title="${CSS.escape(t)}"]`)).length >= 2) {
        p.classList.add(HIDDEN);
        break;
      }
      p = p.parentElement;
    }
  });
}

function build(newChat: HTMLButtonElement) {
  let host = document.querySelector(`.${HOST}`) as HTMLElement | null;
  if (!host) {
    host = document.createElement('div');
    host.className = HOST;
    host.innerHTML = `
      <button type="button" class="inspection-trigger" aria-expanded="false">
        <span class="inspection-left"><span class="inspection-icon">⌁</span><span>Inspection</span></span>
        <span class="inspection-chevron">›</span>
      </button>
      <div class="inspection-clip"><div class="inspection-panel"><div class="inspection-grid"></div></div></div>
    `;
    newChat.insertAdjacentElement('afterend', host);
    const grid = host.querySelector('.inspection-grid') as HTMLElement;
    ITEMS.forEach(([title, label, icon]) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'inspection-item';
      item.dataset.title = title;
      item.innerHTML = `<span class="inspection-item-icon">${icon}</span><span class="inspection-item-label">${label}</span>`;
      item.addEventListener('click', () => source(title)?.click());
      grid.appendChild(item);
    });
    (host.querySelector('.inspection-trigger') as HTMLButtonElement).addEventListener('click', () => {
      const open = host!.classList.toggle('open');
      (host!.querySelector('.inspection-trigger') as HTMLButtonElement).setAttribute('aria-expanded', String(open));
    });
  } else if (host.parentElement !== newChat.parentElement) {
    newChat.insertAdjacentElement('afterend', host);
  }
}

function active() {
  const host = document.querySelector(`.${HOST}`);
  if (!host) return;
  ITEMS.forEach(([title]) => {
    const item = host.querySelector(`[data-title="${CSS.escape(title)}"]`);
    const b = source(title);
    item?.classList.toggle('active', Boolean(b?.className.includes('bg-brand-600')));
  });
}

function sync() {
  styles();
  const aside = document.querySelector('aside');
  if (!aside) return;
  const newChat = Array.from(aside.querySelectorAll('button')).find(b => b.textContent?.trim().includes('New Chat')) as HTMLButtonElement | undefined;
  if (!newChat) return;
  build(newChat);
  hideLegacy();
  active();
}

let queued = false;
function schedule() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; sync(); });
}

if (typeof window !== 'undefined') {
  const start = () => {
    sync();
    const root = document.getElementById('root') || document.body;
    new MutationObserver(schedule).observe(root, {childList:true, subtree:true, attributes:true, attributeFilter:['class']});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
}
