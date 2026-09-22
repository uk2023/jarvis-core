const ITEMS = [
  ['Monitor (System Telemetry & Vitals)', 'Monitor', '◉'],
  ['Trace Inspector (Turn Execution & Latency Waterfall)', 'Trace', '⌁'],
  ['Memory & Database (Schema Contracts & Evolution DB)', 'Memory & DB', '▣'],
  ['System Reasoning (Overnight Learning & Self-Improvement)', 'Reasoning', '✦'],
  ['Organs (Organ Introspection & Heartbeat Network)', 'Organs', '◇'],
  ['Virtual CLI (Diagnostic Shell & Terminal)', 'Virtual CLI', '>_'],
] as const;

const STYLE_ID = 'jarvis-inspection-styles';
const HOST_CLASS = 'jarvis-inspection-host';
const SELECTED_ATTR = 'data-jarvis-inspection-selected';
const HEADER_SEARCH_CLASS = 'jarvis-header-search';
const HEADER_SEARCH_OPEN = 'jarvis-header-search-open';

function installStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .${HOST_CLASS}{display:block!important;width:100%;margin-top:8px;position:relative;z-index:50;visibility:visible!important;opacity:1!important;}
    .jarvis-inspection-trigger{width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border:1px solid var(--jarvis-border,#263044);border-radius:11px;background:var(--jarvis-surface,#101522);color:var(--jarvis-text,#e5e7eb);font-size:11px;font-weight:700;cursor:pointer;}
    .jarvis-inspection-trigger:hover{background:var(--jarvis-surface-raised,#171d2b);}
    .jarvis-inspection-trigger-left{display:flex;align-items:center;gap:7px;min-width:0;}
    .jarvis-inspection-trigger-icon{width:18px;height:18px;border-radius:6px;display:flex;align-items:center;justify-content:center;background:color-mix(in srgb,var(--jarvis-accent,#3b82f6) 14%,transparent);color:var(--jarvis-accent,#3b82f6);}
    .jarvis-inspection-chevron{font-size:13px;line-height:1;transition:transform .22s ease;color:var(--jarvis-text-muted,#94a3b8);}
    .jarvis-inspection-host.is-open .jarvis-inspection-chevron{transform:rotate(90deg);}
    .jarvis-inspection-clip{display:grid;grid-template-rows:0fr;transition:grid-template-rows .28s cubic-bezier(.22,1,.36,1);}
    .jarvis-inspection-host.is-open .jarvis-inspection-clip{grid-template-rows:1fr;}
    .jarvis-inspection-panel{min-height:0;overflow:hidden;}
    .jarvis-inspection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;padding:7px 0 1px;}
    .jarvis-inspection-item{min-width:0;height:46px;border:1px solid var(--jarvis-border,#263044);border-radius:10px;background:var(--jarvis-surface,#101522);color:var(--jarvis-text-muted,#94a3b8);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:4px 2px;cursor:pointer;}
    .jarvis-inspection-item:hover{background:var(--jarvis-surface-raised,#171d2b);color:var(--jarvis-text,#e5e7eb);border-color:var(--jarvis-border-strong,#475569);}
    .jarvis-inspection-item.is-active{background:var(--jarvis-accent,#3b82f6);border-color:var(--jarvis-accent,#3b82f6);color:#fff;}
    .jarvis-inspection-item-icon{font-size:13px;font-weight:800;line-height:1;}
    .jarvis-inspection-item-label{font-size:8px;font-weight:700;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}

    /* Remove the legacy sidebar search without leaving layout space. */
    .jarvis-legacy-chat-search{display:none!important;}

    /* Header search: right-side icon expands left across the complete header. */
    .${HEADER_SEARCH_CLASS}{position:absolute;inset:0;z-index:90;display:flex;align-items:center;justify-content:flex-end;padding:0 12px 0 0;pointer-events:none;overflow:hidden;background:var(--jarvis-surface-raised);transform-origin:right center;transform:scaleX(0);opacity:0;transition:transform .28s cubic-bezier(.22,1,.36,1),opacity .18s ease;}
    .${HEADER_SEARCH_CLASS}.${HEADER_SEARCH_OPEN}{transform:scaleX(1);opacity:1;pointer-events:auto;}
    .jarvis-header-search-field{position:absolute;inset:0;display:flex;align-items:center;padding:0 52px 0 18px;}
    .jarvis-header-search-input{width:100%;height:38px;border:1px solid var(--jarvis-border-strong,#475569);border-radius:12px;background:var(--jarvis-surface,#101522);color:var(--jarvis-text,#e5e7eb);outline:none;padding:0 52px 0 14px;font-size:13px;box-shadow:0 8px 28px rgba(0,0,0,.16);}
    .jarvis-header-search-input::placeholder{color:var(--jarvis-text-muted,#94a3b8);}
    .jarvis-header-search-input:focus{border-color:var(--jarvis-accent,#3b82f6);box-shadow:0 0 0 2px color-mix(in srgb,var(--jarvis-accent,#3b82f6) 16%,transparent),0 8px 28px rgba(0,0,0,.16);}
    .jarvis-header-search-button{position:relative;z-index:2;width:36px;height:36px;border:0;border-radius:10px;background:transparent;color:var(--jarvis-text-muted,#94a3b8);display:flex;align-items:center;justify-content:center;cursor:pointer;flex:0 0 auto;}
    .jarvis-header-search-button:hover{color:var(--jarvis-text,#e5e7eb);background:var(--jarvis-surface,#101522);}
    .jarvis-header-search-collapsed{position:absolute;right:12px;top:50%;transform:translateY(-50%);z-index:91;width:36px;height:36px;border:0;border-radius:10px;background:transparent;color:var(--jarvis-text-muted,#94a3b8);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:background .18s ease,color .18s ease;}
    .jarvis-header-search-collapsed:hover{background:var(--jarvis-surface,#101522);color:var(--jarvis-text,#e5e7eb);}
    @media(max-width:767px){
      .${HOST_CLASS}{margin-top:7px;}.jarvis-inspection-grid{gap:5px;}.jarvis-inspection-item{height:43px;}.jarvis-inspection-item-label{font-size:7.5px;}
      .${HEADER_SEARCH_CLASS}{padding-right:8px;}.jarvis-header-search-field{padding-left:10px;padding-right:46px;}.jarvis-header-search-input{height:36px;}
      .jarvis-header-search-collapsed{right:8px;}
    }
  `;
  document.head.appendChild(style);
}

function getAdminButton(title: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll('button[title]')).find(
    button => button.getAttribute('title') === title,
  ) as HTMLButtonElement | null;
}

function getLegacySubheader(): HTMLElement | null {
  const monitor = getAdminButton(ITEMS[0][0]);
  if (!monitor) return null;
  const subheader = monitor.parentElement?.parentElement as HTMLElement | null;
  if (!subheader || subheader.classList.contains(HOST_CLASS)) return null;
  return subheader;
}

function setLegacySubheaderVisible(visible: boolean) {
  const subheader = getLegacySubheader();
  if (!subheader) return;
  subheader.style.display = '';
  subheader.dataset.jarvisLegacySubheader = 'visible';
}

function buildHeaderSearch() {
  const header = document.querySelector('#app-root header') as HTMLElement | null;
  if (!header || header.querySelector(`.${HEADER_SEARCH_CLASS}`)) return;

  header.style.position = 'relative';

  const collapsed = document.createElement('button');
  collapsed.type = 'button';
  collapsed.className = 'jarvis-header-search-collapsed';
  collapsed.title = 'Search chats';
  collapsed.setAttribute('aria-label', 'Search chats');
  collapsed.innerHTML = '<span aria-hidden="true">⌕</span>';

  const overlay = document.createElement('div');
  overlay.className = HEADER_SEARCH_CLASS;
  overlay.innerHTML = `
    <div class="jarvis-header-search-field">
      <input class="jarvis-header-search-input" type="search" autocomplete="off" spellcheck="false" placeholder="Search chats..." aria-label="Search chats" />
    </div>
    <button type="button" class="jarvis-header-search-button" title="Search chats" aria-label="Search chats"><span aria-hidden="true">⌕</span></button>
  `;
  header.appendChild(overlay);
  header.appendChild(collapsed);

  const input = overlay.querySelector('.jarvis-header-search-input') as HTMLInputElement;
  const button = overlay.querySelector('.jarvis-header-search-button') as HTMLButtonElement;

  const getLegacySearchInput = () =>
    document.querySelector('aside input[placeholder="Search chats..."]') as HTMLInputElement | null;

  const setLegacySearch = (value: string) => {
    const legacy = getLegacySearchInput();
    if (!legacy) return;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(legacy, value);
    legacy.dispatchEvent(new Event('input', { bubbles: true }));
  };

  const close = () => {
    overlay.classList.remove(HEADER_SEARCH_OPEN);
    collapsed.style.visibility = 'visible';
    input.blur();
  };

  const open = () => {
    overlay.classList.add(HEADER_SEARCH_OPEN);
    collapsed.style.visibility = 'hidden';
    requestAnimationFrame(() => input.focus());
  };

  collapsed.addEventListener('click', open);
  button.addEventListener('click', () => input.focus());
  input.addEventListener('input', () => setLegacySearch(input.value));
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      input.value = '';
      setLegacySearch('');
      close();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && overlay.classList.contains(HEADER_SEARCH_OPEN)) {
      event.preventDefault();
      input.value = '';
      setLegacySearch('');
      close();
    }
  });
}

function hideLegacySidebarSearch() {
  const input = document.querySelector('aside input[placeholder="Search chats..."]') as HTMLInputElement | null;
  if (!input) return;
  const wrapper = input.parentElement?.parentElement as HTMLElement | null;
  if (wrapper) wrapper.classList.add('jarvis-legacy-chat-search');
}

function buildHost(newChat: HTMLButtonElement) {
  const existing = document.querySelector(`.${HOST_CLASS}`);
  if (existing) {
    if (existing.parentElement !== newChat.parentElement) newChat.insertAdjacentElement('afterend', existing);
    return;
  }

  const host = document.createElement('div');
  host.className = HOST_CLASS;
  host.innerHTML = `
    <button type="button" class="jarvis-inspection-trigger" aria-expanded="false" aria-controls="jarvis-inspection-panel">
      <span class="jarvis-inspection-trigger-left">
        <span class="jarvis-inspection-trigger-icon">⌁</span>
        <span>Inspection</span>
      </span>
      <span class="jarvis-inspection-chevron">›</span>
    </button>
    <div class="jarvis-inspection-clip">
      <div class="jarvis-inspection-panel" id="jarvis-inspection-panel">
        <div class="jarvis-inspection-grid"></div>
      </div>
    </div>
  `;
  newChat.insertAdjacentElement('afterend', host);

  const trigger = host.querySelector('.jarvis-inspection-trigger') as HTMLButtonElement;
  const grid = host.querySelector('.jarvis-inspection-grid') as HTMLElement;

  ITEMS.forEach(([title, label, icon]) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'jarvis-inspection-item';
    item.title = title;
    item.innerHTML = `<span class="jarvis-inspection-item-icon" aria-hidden="true">${icon}</span><span class="jarvis-inspection-item-label">${label}</span>`;
    item.addEventListener('click', () => {
      document.body.setAttribute(SELECTED_ATTR, title);
      setLegacySubheaderVisible(true);
      getAdminButton(title)?.click();
      syncActiveState();
    });
    grid.appendChild(item);
  });

  trigger.addEventListener('click', () => {
    const open = host.classList.toggle('is-open');
    trigger.setAttribute('aria-expanded', String(open));
  });
}

function syncActiveState() {
  const host = document.querySelector(`.${HOST_CLASS}`);
  if (!host) return;
  const selected = document.body.getAttribute(SELECTED_ATTR);
  ITEMS.forEach(([title]) => {
    const source = getAdminButton(title);
    const item = host.querySelector(`.jarvis-inspection-item[title="${title}"]`) as HTMLElement | null;
    if (item) {
      const active = selected === title || !!source?.className.includes('bg-brand-600');
      item.classList.toggle('is-active', active);
    }
  });
}

function sync() {
  installStyles();
  buildHeaderSearch();
  hideLegacySidebarSearch();

  const aside = document.querySelector('aside');
  if (!aside) return;
  const newChat = Array.from(aside.querySelectorAll('button')).find(
    button => button.textContent?.trim().includes('New Chat'),
  ) as HTMLButtonElement | undefined;
  if (!newChat) return;
  buildHost(newChat);
  setLegacySubheaderVisible(true);
  syncActiveState();
}

let scheduled = false;
function scheduleSync() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    sync();
  });
}

if (typeof window !== 'undefined') {
  const start = () => {
    document.addEventListener('click', event => {
      const target = event.target as Element | null;
      const button = target?.closest('button[title]') as HTMLButtonElement | null;
      if (!button) return;
      const title = button.getAttribute('title') || '';
      if (ITEMS.some(([itemTitle]) => itemTitle === title)) return;
      /* The admin quick-nav is intentionally persistent; do not hide it on Home/Chat. */
    }, true);
    sync();
    const root = document.getElementById('root') || document.body;
    const observer = new MutationObserver(scheduleSync);
    observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
}
