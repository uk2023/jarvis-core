const ADMIN_TITLES = [
  'Monitor (System Telemetry & Vitals)',
  'Trace Inspector (Turn Execution & Latency Waterfall)',
  'Memory & Database (Schema Contracts & Evolution DB)',
  'System Reasoning (Overnight Learning & Self-Improvement)',
  'Organs (Organ Introspection & Heartbeat Network)',
  'Virtual CLI (Diagnostic Shell & Terminal)',
];

function addStyles() {
  if (document.getElementById('jarvis-sidebar-enhancement-style')) return;
  const style = document.createElement('style');
  style.id = 'jarvis-sidebar-enhancement-style';
  style.textContent = `
    .jarvis-sidebar-search-shell{position:absolute;inset:0;z-index:80;display:flex;align-items:center;padding:0 12px;background:var(--jarvis-surface-raised);border-bottom:1px solid var(--jarvis-border);opacity:0;pointer-events:none;transform:translateX(8px);transition:opacity .18s ease,transform .22s ease;}
    .jarvis-sidebar-search-shell.is-open{opacity:1;pointer-events:auto;transform:none;}
    .jarvis-sidebar-search-input{flex:1;min-width:0;height:38px;border:0;outline:0;background:transparent;color:var(--jarvis-text);font-size:14px;padding:0 10px;}
    .jarvis-sidebar-search-icon{width:32px;height:32px;display:flex;align-items:center;justify-content:center;color:var(--jarvis-text-muted);flex:0 0 32px;}
    .jarvis-sidebar-search-button{position:relative;z-index:81;}
    .jarvis-sidebar-inspection-trigger{width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px;padding:8px 10px;border:1px solid var(--jarvis-border);border-radius:11px;background:var(--jarvis-surface);color:var(--jarvis-text);font-size:11px;font-weight:700;cursor:pointer;transition:background .18s,border-color .18s,transform .18s;}
    .jarvis-sidebar-inspection-trigger:hover{background:var(--jarvis-surface-raised);border-color:var(--jarvis-border-strong);transform:translateY(-1px);}
    .jarvis-sidebar-inspection-trigger svg{transition:transform .22s ease;}
    .jarvis-sidebar-inspection-trigger.is-open svg{transform:rotate(180deg);}
    .jarvis-sidebar-inspection-panel{display:grid!important;grid-template-rows:0fr;opacity:0;overflow:hidden!important;padding:0!important;margin:0!important;border:0!important;transform:translateY(-3px);transition:grid-template-rows .26s ease,opacity .2s ease,transform .26s ease,padding .26s ease,margin .26s ease;}
    .jarvis-sidebar-inspection-panel > *{min-height:0;overflow:hidden;}
    .jarvis-sidebar-inspection-panel.is-open{grid-template-rows:1fr;opacity:1;transform:none;padding:7px!important;margin-top:5px!important;border:1px solid var(--jarvis-border)!important;}
    .jarvis-sidebar-inspection-panel .jarvis-admin-sidebar-nav-host{width:100%!important;padding:0!important;}
    .jarvis-sidebar-inspection-panel .jarvis-admin-sidebar-nav{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;width:100%;}
    .jarvis-sidebar-logo .jarvis-black-hole{transform:scale(.30);transform-origin:center;animation-duration:6s;filter:drop-shadow(0 0 15px rgba(55,100,220,.24));margin:0;width:178px;height:178px;}
    .jarvis-sidebar-logo{width:34px;height:34px;display:flex;align-items:center;justify-content:center;overflow:visible;flex:0 0 34px;}
    .jarvis-sidebar-logo .jarvis-black-hole:before{width:166px;height:166px}.jarvis-sidebar-logo .jarvis-black-hole:after{width:145px;height:145px}.jarvis-sidebar-logo .jarvis-core-glow{width:116px;height:116px}.jarvis-sidebar-logo .jarvis-core-void{width:69px;height:69px}.jarvis-sidebar-logo .jarvis-accretion{width:170px;height:61px}.jarvis-sidebar-logo .orbit-a{width:158px;height:59px}.jarvis-sidebar-logo .orbit-b{width:181px;height:74px}.jarvis-sidebar-logo .orbit-c{width:151px;height:47px}
  `;
  document.head.appendChild(style);
}

function blackHoleMarkup() {
  const logo = document.createElement('div');
  logo.className = 'jarvis-sidebar-logo';
  logo.setAttribute('aria-label', 'JARVIS cognitive core');
  logo.innerHTML = `<div class="jarvis-black-hole"><div class="jarvis-orbit orbit-a"></div><div class="jarvis-orbit orbit-b"></div><div class="jarvis-orbit orbit-c"></div><div class="jarvis-accretion"></div><div class="jarvis-core-glow"></div><div class="jarvis-core-void"><span></span><span></span><span></span></div></div>`;
  return logo;
}

function setupHeaderSearch(header: HTMLElement, sidebar: HTMLElement | null) {
  if (header.dataset.jarvisSearchReady === '1') return;
  header.dataset.jarvisSearchReady = '1';
  header.style.position = 'relative';

  const rightControls = header.lastElementChild as HTMLElement | null;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'jarvis-sidebar-search-button p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 text-slate-500 dark:text-slate-400 transition cursor-pointer';
  button.setAttribute('aria-label', 'Search chats');
  button.title = 'Search chats';
  button.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>';
  (rightControls || header).prepend(button);

  const shell = document.createElement('div');
  shell.className = 'jarvis-sidebar-search-shell';
  shell.innerHTML = '<div class="jarvis-sidebar-search-icon"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg></div><input class="jarvis-sidebar-search-input" type="text" autocomplete="off" placeholder="Search chats..." aria-label="Search chats"><div class="jarvis-sidebar-search-icon" aria-hidden="true"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg></div>';
  header.appendChild(shell);
  const input = shell.querySelector('input') as HTMLInputElement;

  const apply = () => {
    const q = input.value.trim().toLowerCase();
    if (sidebar) {
      sidebar.querySelectorAll('button[title="Chat options"]').forEach(action => {
        const row = action.closest('.group') as HTMLElement | null;
        if (row) row.style.display = !q || row.textContent?.toLowerCase().includes(q) ? '' : 'none';
      });
    }
  };
  const close = () => {
    shell.classList.remove('is-open');
    input.value = '';
    apply();
    button.focus({preventScroll:true});
  };
  button.addEventListener('click', () => { shell.classList.add('is-open'); input.focus(); });
  input.addEventListener('input', apply);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && shell.classList.contains('is-open')) close(); });
}

function setupSidebar(sidebar: HTMLElement) {
  const firstRun = sidebar.dataset.jarvisEnhancementsReady !== '1';
  if (firstRun) sidebar.dataset.jarvisEnhancementsReady = '1';

  if (firstRun) {
    const brandButton = Array.from(sidebar.querySelectorAll('button')).find(b => b.getAttribute('title') === 'Return to Home') as HTMLElement | undefined;
    if (brandButton) {
      brandButton.querySelectorAll('span').forEach(s => s.remove());
      const oldLogo = brandButton.firstElementChild;
      oldLogo?.remove();
      brandButton.prepend(blackHoleMarkup());
      brandButton.classList.remove('gap-2');
    }

    const oldSearch = sidebar.querySelector('input[placeholder="Search chats..."]') as HTMLInputElement | null;
    if (oldSearch) {
      const legacyWrap = oldSearch.closest('div');
      if (legacyWrap) (legacyWrap as HTMLElement).style.display = 'none';
    }

    const newChat = Array.from(sidebar.querySelectorAll('button')).find(b => b.textContent?.trim() === 'New Chat') as HTMLElement | undefined;
    if (newChat && !sidebar.querySelector('.jarvis-sidebar-inspection-trigger')) {
      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'jarvis-sidebar-inspection-trigger';
      trigger.innerHTML = '<span>Inspection</span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"></path></svg>';
      const panel = document.createElement('div');
      panel.className = 'jarvis-sidebar-inspection-panel';
      newChat.insertAdjacentElement('afterend', trigger);
      trigger.insertAdjacentElement('afterend', panel);
      trigger.addEventListener('click', () => {
        panel.classList.toggle('is-open');
        trigger.classList.toggle('is-open');
        const h = panel.querySelector('.jarvis-admin-sidebar-nav-host') as HTMLElement | null;
        if (h) h.style.display = panel.classList.contains('is-open') ? '' : 'none';
      });
    }
  }

  const inspectionPanel = sidebar.querySelector('.jarvis-sidebar-inspection-panel') as HTMLElement | null;
  const navHost = sidebar.querySelector('.jarvis-admin-sidebar-nav-host') as HTMLElement | null;
  if (inspectionPanel && navHost && navHost.parentElement !== inspectionPanel) {
    inspectionPanel.appendChild(navHost);
    navHost.style.display = inspectionPanel.classList.contains('is-open') ? '' : 'none';
  }
}

function sync() {
  addStyles();
  const root = document.getElementById('app-root');
  if (!root) return;
  const sidebar = root.querySelector('aside') as HTMLElement | null;
  const header = root.querySelector('header') as HTMLElement | null;
  if (sidebar) setupSidebar(sidebar);
  if (header) setupHeaderSearch(header, sidebar);

  ADMIN_TITLES.forEach(title => {
    const button = Array.from(root.querySelectorAll('button[title]')).find(b => b.getAttribute('title') === title) as HTMLElement | undefined;
    if (button) {
      button.style.position = 'absolute';
      button.style.width = '1px';
      button.style.height = '1px';
      button.style.opacity = '0';
      button.style.pointerEvents = 'none';
      button.style.overflow = 'hidden';
    }
  });
  const adminButton = root.querySelector('button[title="Monitor (System Telemetry & Vitals)"]');
  const subHeader = adminButton?.parentElement?.parentElement as HTMLElement | null;
  if (subHeader) subHeader.style.display = 'none';
}

const observer = new MutationObserver(() => sync());
const boot = () => {
  sync();
  observer.observe(document.getElementById('app-root') || document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['class','style']});
};
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true}); else boot();
