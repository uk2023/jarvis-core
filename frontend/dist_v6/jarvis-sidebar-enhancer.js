(() => {
  const ITEMS = [
    ['Monitor (System Telemetry & Vitals)', 'Monitor', 'activity'],
    ['Trace Inspector (Turn Execution & Latency Waterfall)', 'Trace Inspector', 'trace'],
    ['Memory & Database (Schema Contracts & Evolution DB)', 'Memory & DB', 'database'],
    ['System Reasoning (Overnight Learning & Self-Improvement)', 'Reasoning', 'sparkles'],
    ['Organs (Organ Introspection & Heartbeat Network)', 'Organs', 'layers'],
    ['Virtual CLI (Diagnostic Shell & Terminal)', 'Virtual CLI', 'terminal'],
  ];

  const icon = name => {
    const paths = {
      activity: '<path d="M3 12h4l2-7 4 14 2-7h6"/>',
      trace: '<path d="M4 6h6v5H4zM14 13h6v5h-6zM10 8h4M10 16h4M12 8v8"/>',
      database: '<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/>',
      sparkles: '<path d="m12 3 1.4 5.6L19 10l-5.6 1.4L12 17l-1.4-5.6L5 10l5.6-1.4zM19 17l.5 2.5L22 20l-2.5.5L19 23l-.5-2.5L16 20l2.5-.5z"/>',
      layers: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
      terminal: '<path d="m5 7 5 5-5 5M12 17h7"/>',
      search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
      x: '<path d="M6 6l12 12M18 6 6 18"/>',
      chevron: '<path d="m7 10 5 5 5-5"/>',
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || ''}</svg>`;
  };

  const css = `
    .jarvis-sidebar-v2{position:relative}
    .jarvis-sidebar-v2-brand{position:relative;display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;min-width:0;height:38px}
    .jarvis-sidebar-v2-logo-button{width:38px;height:38px;padding:0;border:0;background:transparent;color:var(--jarvis-text);display:grid;place-items:center;cursor:pointer;position:relative;z-index:2}
    .jarvis-sidebar-v2-logo-core{width:38px;height:38px;display:grid;place-items:center;overflow:hidden;position:relative;border-radius:50%}
    .jarvis-sidebar-v2-logo-core .jarvis-black-hole{width:178px;height:178px;margin:0;transform:scale(.205);transform-origin:center;filter:drop-shadow(0 0 34px rgba(55,100,220,.32));animation:jarvis-core-float 6s ease-in-out infinite}
    .jarvis-sidebar-v2-logo-core .jarvis-black-hole:before{width:166px;height:166px}
    .jarvis-sidebar-v2-logo-core .jarvis-black-hole:after{width:145px;height:145px}
    .jarvis-sidebar-v2-logo-core .jarvis-core-glow{width:116px;height:116px}
    .jarvis-sidebar-v2-logo-core .jarvis-core-void{width:69px;height:69px}
    .jarvis-sidebar-v2-logo-core .jarvis-accretion{width:170px;height:61px}
    .jarvis-sidebar-v2-logo-core .jarvis-orbit.orbit-a{width:158px;height:59px}
    .jarvis-sidebar-v2-logo-core .jarvis-orbit.orbit-b{width:181px;height:74px}
    .jarvis-sidebar-v2-logo-core .jarvis-orbit.orbit-c{width:151px;height:47px}

    .jarvis-sidebar-v2-actions{display:flex;align-items:center;gap:4px;margin-left:auto;position:relative;z-index:4}
    .jarvis-sidebar-v2-iconbtn{width:30px;height:30px;border:0;border-radius:9px;background:transparent;color:var(--jarvis-text-muted);display:grid;place-items:center;cursor:pointer;transition:background .18s ease,color .18s ease,transform .18s ease}
    .jarvis-sidebar-v2-iconbtn:hover{background:var(--jarvis-surface-raised);color:var(--jarvis-text);transform:translateY(-1px)}
    .jarvis-sidebar-v2-iconbtn svg{width:16px;height:16px}

    /* Search opens leftward from its normal icon position. The search icon stays at the right edge; close is a separate button. */
    .jarvis-sidebar-v2-search{position:absolute;left:calc(100% - 68px);top:3px;display:grid;grid-template-columns:minmax(0,1fr) 30px;align-items:center;width:30px;height:32px;overflow:hidden;border:1px solid transparent;border-radius:10px;background:transparent;z-index:5;transition:left .32s cubic-bezier(.2,.8,.2,1),width .32s cubic-bezier(.2,.8,.2,1),background .2s,border-color .2s,box-shadow .2s}
    .jarvis-sidebar-v2-search.is-open{left:0;width:calc(100% - 34px);background:var(--jarvis-surface);border-color:var(--jarvis-border);box-shadow:0 8px 24px rgba(0,0,0,.12)}
    .jarvis-sidebar-v2-search input{grid-column:1;grid-row:1;min-width:0;width:100%;height:30px;border:0;outline:0;background:transparent;color:var(--jarvis-text);font-size:12px;opacity:0;padding:0 8px;transition:opacity .16s ease}
    .jarvis-sidebar-v2-search.is-open input{opacity:1}
    .jarvis-sidebar-v2-search button{grid-column:2;grid-row:1;border:0;background:transparent;color:var(--jarvis-text-muted);height:30px;width:30px;display:grid;place-items:center;cursor:pointer}
    .jarvis-sidebar-v2-search button svg{width:16px;height:16px}

    .jarvis-sidebar-v2-native-search{display:none!important}

    .jarvis-inspection{margin-top:8px;border:1px solid var(--jarvis-border);border-radius:13px;background:var(--jarvis-surface);overflow:hidden;transition:max-height .3s cubic-bezier(.2,.8,.2,1),opacity .2s ease,transform .3s ease}
    .jarvis-inspection.is-collapsed{max-height:42px}
    .jarvis-inspection.is-open{max-height:190px}
    .jarvis-inspection-head{height:40px;width:100%;display:flex;align-items:center;gap:8px;padding:0 10px;border:0;background:transparent;color:var(--jarvis-text);font-size:11px;font-weight:700;cursor:pointer}
    .jarvis-inspection-head .label{flex:1;text-align:left}
    .jarvis-inspection-head svg{width:15px;height:15px;transition:transform .25s ease}
    .jarvis-inspection.is-open .jarvis-inspection-head svg:last-child{transform:rotate(180deg)}
    .jarvis-inspection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:0 7px 7px;opacity:1;transform:translateY(0);transition:opacity .2s ease,transform .25s ease}
    .jarvis-inspection.is-collapsed .jarvis-inspection-grid{opacity:0;transform:translateY(-5px);pointer-events:none}
    .jarvis-inspection-item{height:48px;border:1px solid var(--jarvis-border);border-radius:10px;background:transparent;color:var(--jarvis-text-muted);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;cursor:pointer;transition:all .16s ease}
    .jarvis-inspection-item:hover{background:var(--jarvis-surface-raised);color:var(--jarvis-text);border-color:var(--jarvis-border-strong);transform:translateY(-1px)}
    .jarvis-inspection-item.is-active{background:var(--jarvis-accent);border-color:var(--jarvis-accent);color:#fff;box-shadow:0 5px 14px color-mix(in srgb,var(--jarvis-accent) 25%,transparent)}
    .jarvis-inspection-item svg{width:15px;height:15px}.jarvis-inspection-item span{font-size:7px;font-weight:700;white-space:nowrap}

    #app-root > div > header + div.jarvis-admin-subheader-hidden{display:none!important}
    #app-root > div > header + div.jarvis-admin-subheader-active{display:flex!important}
    @media(max-width:767px){.jarvis-inspection-item{height:44px}.jarvis-sidebar-v2-logo-core{width:34px;height:34px}.jarvis-sidebar-v2-brand{height:36px}.jarvis-sidebar-v2-search{top:2px}}
  `;

  function injectStyle() {
    if (document.getElementById('jarvis-sidebar-v2-style')) document.getElementById('jarvis-sidebar-v2-style').textContent = css;
    else {
      const style = document.createElement('style');
      style.id = 'jarvis-sidebar-v2-style';
      style.textContent = css;
      document.head.appendChild(style);
    }
  }

  function findAdminButton(title) {
    return Array.from(document.querySelectorAll('button[title]')).find(b => b.getAttribute('title') === title);
  }

  function activeAdmin() {
    return ITEMS.some(([title]) => {
      const b = findAdminButton(title);
      return b && b.className.includes('bg-brand-600');
    });
  }

  function syncSubheader() {
    const root = document.getElementById('app-root');
    if (!root) return;
    const header = root.querySelector('header');
    if (!header) return;
    const sub = header.nextElementSibling;
    if (!sub || !sub.querySelector) return;
    const hasAdminButtons = ITEMS.some(([title]) => !!findAdminButton(title));
    if (!hasAdminButtons) return;
    const active = activeAdmin();
    sub.classList.toggle('jarvis-admin-subheader-active', active);
    sub.classList.toggle('jarvis-admin-subheader-hidden', !active);
  }

  function hideNativeSearch(top) {
    const native = Array.from(top.querySelectorAll('input[placeholder="Search chats..."]')).find(input => !input.closest('.jarvis-sidebar-v2-search'));
    if (!native) return;
    const container = native.closest('div');
    if (container) container.classList.add('jarvis-sidebar-v2-native-search');
  }

  function buildSidebar(aside) {
    if (aside.querySelector('.jarvis-sidebar-v2')) return;
    const top = aside.firstElementChild;
    if (!top) return;
    top.classList.add('jarvis-sidebar-v2');
    const oldBrand = top.querySelector('button[title="Return to Home"]');
    const newChat = Array.from(top.querySelectorAll('button')).find(b => b.textContent?.includes('New Chat'));
    if (!oldBrand || !newChat) return;

    const brandRow = document.createElement('div');
    brandRow.className = 'jarvis-sidebar-v2-brand';

    const logoButton = document.createElement('button');
    logoButton.type = 'button';
    logoButton.title = 'Return to Home';
    logoButton.className = 'jarvis-sidebar-v2-logo-button';
    logoButton.innerHTML = '<span class="jarvis-sidebar-v2-logo-core" aria-hidden="true"><span class="jarvis-black-hole"><span class="jarvis-orbit orbit-a"></span><span class="jarvis-orbit orbit-b"></span><span class="jarvis-orbit orbit-c"></span><span class="jarvis-accretion"></span><span class="jarvis-core-glow"></span><span class="jarvis-core-void"><span></span><span></span><span></span></span></span></span>';
    logoButton.onclick = () => oldBrand.click();

    const actions = document.createElement('div');
    actions.className = 'jarvis-sidebar-v2-actions';

    const searchWrap = document.createElement('div');
    searchWrap.className = 'jarvis-sidebar-v2-search';
    searchWrap.setAttribute('aria-label', 'Search chats');

    const searchInput = document.createElement('input');
    searchInput.type = 'search';
    searchInput.placeholder = 'Search chats...';
    searchInput.setAttribute('aria-label', 'Search chats');

    const searchBtn = document.createElement('button');
    searchBtn.type = 'button';
    searchBtn.title = 'Search chats';
    searchBtn.innerHTML = icon('search');

    searchWrap.append(searchInput, searchBtn);

    const openSearch = () => {
      searchWrap.classList.add('is-open');
      window.setTimeout(() => searchInput.focus(), 120);
    };
    const closeSearch = () => {
      searchWrap.classList.remove('is-open');
      searchInput.blur();
    };
    searchBtn.onclick = () => {
      if (searchWrap.classList.contains('is-open')) searchInput.focus();
      else openSearch();
    };
    searchInput.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeSearch();
    });
    searchInput.addEventListener('input', () => {
      const native = Array.from(top.querySelectorAll('input[placeholder="Search chats..."]')).find(input => input !== searchInput);
      if (native) {
        native.value = searchInput.value;
        native.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.title = 'Close sidebar';
    closeBtn.className = 'jarvis-sidebar-v2-iconbtn';
    closeBtn.innerHTML = icon('x');
    closeBtn.onclick = () => {
      const collapse = top.querySelector('button[title="Collapse sidebar"]');
      const mobileClose = top.querySelector('button[title="Close sidebar"]');
      if (mobileClose && mobileClose !== closeBtn) mobileClose.click();
      else if (collapse) collapse.click();
    };

    actions.append(closeBtn);
    brandRow.append(logoButton, actions, searchWrap);

    oldBrand.style.display = 'none';
    const collapseBtn = top.querySelector('button[title="Collapse sidebar"],button[title="Expand sidebar"]');
    if (collapseBtn) collapseBtn.style.display = 'none';
    const mobileClose = top.querySelector('button[title="Close sidebar"]');
    if (mobileClose && mobileClose !== closeBtn) mobileClose.style.display = 'none';
    top.insertBefore(brandRow, top.firstChild);
    hideNativeSearch(top);

    const inspection = document.createElement('section');
    inspection.className = 'jarvis-inspection is-collapsed';
    const head = document.createElement('button');
    head.type = 'button';
    head.className = 'jarvis-inspection-head';
    head.innerHTML = `${icon('layers')}<span class="label">Inspection</span>${icon('chevron')}`;
    const grid = document.createElement('div');
    grid.className = 'jarvis-inspection-grid';

    ITEMS.forEach(([title, label, iconName]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'jarvis-inspection-item';
      button.title = label;
      button.innerHTML = `${icon(iconName)}<span>${label}</span>`;
      button.onclick = () => {
        const target = findAdminButton(title);
        if (target) target.click();
        syncSubheader();
        syncActive();
      };
      grid.appendChild(button);
    });

    head.onclick = () => {
      const open = inspection.classList.toggle('is-open');
      inspection.classList.toggle('is-collapsed', !open);
    };

    inspection.append(head, grid);
    newChat.insertAdjacentElement('afterend', inspection);

    function syncActive() {
      ITEMS.forEach(([title], i) => {
        const target = findAdminButton(title);
        grid.children[i].classList.toggle('is-active', !!target && target.className.includes('bg-brand-600'));
      });
    }

    const observer = new MutationObserver(() => {
      syncSubheader();
      syncActive();
    });
    observer.observe(document.getElementById('app-root') || document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['class', 'style'],
    });
    syncActive();
  }

  function boot() {
    injectStyle();
    const aside = document.querySelector('#app-root aside');
    if (aside) buildSidebar(aside);
    syncSubheader();
  }

  const observer = new MutationObserver(boot);
  observer.observe(document.documentElement, { subtree: true, childList: true });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
