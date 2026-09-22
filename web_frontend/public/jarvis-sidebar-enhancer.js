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
    .jarvis-sidebar-v2-brand{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;min-width:0}
    .jarvis-sidebar-v2-logo{width:34px;height:34px;border:1px solid var(--jarvis-border-strong);border-radius:50%;position:relative;display:grid;place-items:center;overflow:hidden;background:radial-gradient(circle at 50% 50%,#02030a 0 25%,transparent 26%),radial-gradient(circle,#050814 30%,#111a2d 55%,transparent 57%);box-shadow:0 0 18px color-mix(in srgb,var(--jarvis-accent) 35%,transparent),inset 0 0 12px rgba(255,255,255,.08);transition:transform .2s ease,box-shadow .2s ease}
    .jarvis-sidebar-v2-logo:before{content:"";position:absolute;width:43px;height:15px;border:2px solid color-mix(in srgb,var(--jarvis-accent) 75%,white);border-radius:50%;transform:rotate(-18deg);filter:blur(.15px);opacity:.9}
    .jarvis-sidebar-v2-logo:after{content:"";position:absolute;width:19px;height:19px;border-radius:50%;background:#000;box-shadow:0 0 9px rgba(0,0,0,.95)}
    .jarvis-sidebar-v2-logo:hover{transform:scale(1.06);box-shadow:0 0 25px color-mix(in srgb,var(--jarvis-accent) 50%,transparent),inset 0 0 14px rgba(255,255,255,.1)}
    .jarvis-sidebar-v2-actions{display:flex;align-items:center;gap:4px;margin-left:auto}
    .jarvis-sidebar-v2-iconbtn{width:30px;height:30px;border:0;border-radius:9px;background:transparent;color:var(--jarvis-text-muted);display:grid;place-items:center;cursor:pointer;transition:background .18s ease,color .18s ease,transform .18s ease}
    .jarvis-sidebar-v2-iconbtn:hover{background:var(--jarvis-surface-raised);color:var(--jarvis-text);transform:translateY(-1px)}
    .jarvis-sidebar-v2-iconbtn svg{width:16px;height:16px}
    .jarvis-sidebar-v2-search{display:grid;grid-template-columns:30px minmax(0,1fr) 30px;align-items:center;gap:3px;width:30px;height:32px;overflow:hidden;border:1px solid transparent;border-radius:10px;transition:width .28s cubic-bezier(.2,.8,.2,1),background .2s,border-color .2s}
    .jarvis-sidebar-v2-search.is-open{width:100%;background:var(--jarvis-surface);border-color:var(--jarvis-border)}
    .jarvis-sidebar-v2-search input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:var(--jarvis-text);font-size:12px;opacity:0;transition:opacity .18s ease}
    .jarvis-sidebar-v2-search.is-open input{opacity:1}
    .jarvis-sidebar-v2-search button{border:0;background:transparent;color:var(--jarvis-text-muted);height:30px;width:30px;display:grid;place-items:center;cursor:pointer}
    .jarvis-sidebar-v2-search button svg{width:15px;height:15px}
    .jarvis-inspection{margin-top:8px;border:1px solid var(--jarvis-border);border-radius:13px;background:var(--jarvis-surface);overflow:hidden;transition:max-height .28s ease,opacity .2s ease,transform .28s ease}
    .jarvis-inspection.is-collapsed{max-height:42px}
    .jarvis-inspection.is-open{max-height:190px}
    .jarvis-inspection-head{height:40px;width:100%;display:flex;align-items:center;gap:8px;padding:0 10px;border:0;background:transparent;color:var(--jarvis-text);font-size:11px;font-weight:700;cursor:pointer}
    .jarvis-inspection-head .label{flex:1;text-align:left}
    .jarvis-inspection-head svg{width:15px;height:15px}
    .jarvis-inspection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:0 7px 7px;opacity:1;transform:translateY(0);transition:opacity .2s ease,transform .25s ease}
    .jarvis-inspection.is-collapsed .jarvis-inspection-grid{opacity:0;transform:translateY(-5px);pointer-events:none}
    .jarvis-inspection-item{height:48px;border:1px solid var(--jarvis-border);border-radius:10px;background:transparent;color:var(--jarvis-text-muted);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;cursor:pointer;transition:all .16s ease}
    .jarvis-inspection-item:hover{background:var(--jarvis-surface-raised);color:var(--jarvis-text);border-color:var(--jarvis-border-strong);transform:translateY(-1px)}
    .jarvis-inspection-item.is-active{background:var(--jarvis-accent);border-color:var(--jarvis-accent);color:#fff;box-shadow:0 5px 14px color-mix(in srgb,var(--jarvis-accent) 25%,transparent)}
    .jarvis-inspection-item svg{width:15px;height:15px}.jarvis-inspection-item span{font-size:7px;font-weight:700;white-space:nowrap}
    #app-root > div > header + div.jarvis-admin-subheader-hidden{display:none!important}
    #app-root > div > header + div.jarvis-admin-subheader-active{display:flex!important}
    @media(max-width:767px){.jarvis-inspection-item{height:44px}.jarvis-sidebar-v2-logo{width:32px;height:32px}}
  `;

  function injectStyle() {
    if (document.getElementById('jarvis-sidebar-v2-style')) return;
    const style = document.createElement('style');
    style.id = 'jarvis-sidebar-v2-style';
    style.textContent = css;
    document.head.appendChild(style);
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
    sub.classList.toggle('jarvis-admin-subheader-active', activeAdmin());
    sub.classList.toggle('jarvis-admin-subheader-hidden', !activeAdmin());
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
    logoButton.className = 'jarvis-sidebar-v2-iconbtn';
    logoButton.style.cssText = 'width:38px;height:38px;';
    logoButton.innerHTML = '<span class="jarvis-sidebar-v2-logo" aria-hidden="true"></span>';
    logoButton.onclick = () => oldBrand.click();

    const actions = document.createElement('div');
    actions.className = 'jarvis-sidebar-v2-actions';

    const searchWrap = document.createElement('div');
    searchWrap.className = 'jarvis-sidebar-v2-search';
    const searchBtn = document.createElement('button');
    searchBtn.type = 'button'; searchBtn.title = 'Search chats'; searchBtn.innerHTML = icon('search');
    const searchInput = document.createElement('input');
    searchInput.type = 'search'; searchInput.placeholder = 'Search chats...';
    searchInput.setAttribute('aria-label','Search chats');
    const searchClose = document.createElement('button');
    searchClose.type = 'button'; searchClose.title = 'Clear search'; searchClose.innerHTML = icon('x');
    searchWrap.append(searchBtn, searchInput, searchClose);
    searchBtn.onclick = () => { searchWrap.classList.add('is-open'); searchInput.focus(); };
    searchInput.addEventListener('input', () => {
      const native = top.querySelector('input[placeholder="Search chats..."]');
      if (native) { native.value = searchInput.value; native.dispatchEvent(new Event('input', {bubbles:true})); }
    });
    searchClose.onclick = () => { searchInput.value=''; const native=top.querySelector('input[placeholder="Search chats..."]'); if(native){native.value='';native.dispatchEvent(new Event('input',{bubbles:true}));} searchWrap.classList.remove('is-open'); };

    const closeBtn = document.createElement('button');
    closeBtn.type='button'; closeBtn.title='Close sidebar'; closeBtn.className='jarvis-sidebar-v2-iconbtn'; closeBtn.innerHTML=icon('x');
    closeBtn.onclick = () => {
      const collapse = top.querySelector('button[title="Collapse sidebar"]');
      const mobileClose = top.querySelector('button[title="Close sidebar"]');
      if (mobileClose && mobileClose !== closeBtn) mobileClose.click(); else if (collapse) collapse.click();
    };
    actions.append(searchWrap, closeBtn);
    brandRow.append(logoButton, actions);

    oldBrand.style.display='none';
    const collapseBtn = top.querySelector('button[title="Collapse sidebar"],button[title="Expand sidebar"]');
    if (collapseBtn) collapseBtn.style.display='none';
    const mobileClose = top.querySelector('button[title="Close sidebar"]');
    if (mobileClose && mobileClose !== closeBtn) mobileClose.style.display='none';
    top.insertBefore(brandRow, top.firstChild);

    const inspection = document.createElement('section');
    inspection.className='jarvis-inspection is-collapsed';
    const head=document.createElement('button'); head.type='button'; head.className='jarvis-inspection-head'; head.innerHTML=`${icon('layers')}<span class="label">Inspection</span>${icon('chevron')}`;
    const grid=document.createElement('div'); grid.className='jarvis-inspection-grid';
    ITEMS.forEach(([title,label,iconName])=>{
      const button=document.createElement('button'); button.type='button'; button.className='jarvis-inspection-item'; button.title=label; button.innerHTML=`${icon(iconName)}<span>${label}</span>`;
      button.onclick=()=>{ const target=findAdminButton(title); if(target) target.click(); syncSubheader(); syncActive(); };
      grid.appendChild(button);
    });
    head.onclick=()=>{ const open=inspection.classList.toggle('is-open'); inspection.classList.toggle('is-collapsed',!open); head.lastElementChild.innerHTML=icon('chevron'); };
    inspection.append(head,grid);
    newChat.insertAdjacentElement('afterend', inspection);

    function syncActive(){
      ITEMS.forEach(([title],i)=>{const target=findAdminButton(title); grid.children[i].classList.toggle('is-active',!!target && target.className.includes('bg-brand-600'));});
    }
    const observer=new MutationObserver(()=>{syncSubheader();syncActive();});
    observer.observe(document.getElementById('app-root')||document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','style']});
    syncActive();
  }

  function boot(){
    injectStyle();
    const aside=document.querySelector('#app-root aside');
    if(aside) buildSidebar(aside);
    syncSubheader();
  }

  const observer=new MutationObserver(boot);
  observer.observe(document.documentElement,{subtree:true,childList:true});
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
