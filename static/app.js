/* Portal Cobaltax — Frontend */

'use strict';

// ---- Password-confirm modal ----
// Usage: const pw = await requirePasswordConfirm('Title', 'Description text');
// Returns the entered password string, or null if the user cancelled.
function requirePasswordConfirm(title, desc) {
  return new Promise(resolve => {
    const overlay  = document.getElementById('pw-confirm-modal');
    const titleEl  = document.getElementById('pw-confirm-title');
    const descEl   = document.getElementById('pw-confirm-desc');
    const input    = document.getElementById('pw-confirm-input');
    const okBtn    = document.getElementById('pw-confirm-ok');
    const cancelFn = () => { close(); resolve(null); };
    const okFn     = () => { const val = input.value; close(); resolve(val); };

    function close() {
      overlay.classList.add('hidden');
      input.value = '';
      okBtn.removeEventListener('click', okFn);
      document.getElementById('pw-confirm-cancel').removeEventListener('click', cancelFn);
      document.getElementById('pw-confirm-close').removeEventListener('click', cancelFn);
      input.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Enter') okFn(); if (e.key === 'Escape') cancelFn(); }

    titleEl.textContent = title;
    descEl.textContent  = desc;
    document.getElementById('pw-confirm-user').textContent = state.user || '';
    overlay.classList.remove('hidden');
    input.focus();
    okBtn.addEventListener('click', okFn);
    document.getElementById('pw-confirm-cancel').addEventListener('click', cancelFn);
    document.getElementById('pw-confirm-close').addEventListener('click', cancelFn);
    input.addEventListener('keydown', onKey);
  });
}

// ---- State ----
const state = {
  user: null,
  isAdmin: false,
  permissions: {},
  portalName: 'Portal Cobaltax',
  currentModule: null,
  lang: 'en',
  translations: {},
  servers: {},
  autoRefresh: true,
  sseSource: null,
  authEnabled: true,
  refreshInterval: 30,
};

// ---- i18n ----
async function loadTranslations(lang) {
  try {
    const r = await fetch(`/api/translations/${lang}`);
    state.translations = await r.json();
    state.lang = lang;
  } catch {
    state.translations = {};
  }
}

function t(key, vars = {}) {
  let s = state.translations[key] || key;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = state.translations[key];
    if (val) el.textContent = val;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.dataset.i18nPlaceholder;
    const val = state.translations[key];
    if (val) el.placeholder = val;
  });
}

// ---- Toast ----
function toast(msg, type = 'info', ms = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ---- Utility ----
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---- API helpers ----
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (r.status === 401) { showLogin(); throw new Error('Unauthenticated'); }
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

// ---- Portal name ----
function applyPortalName(name) {
  state.portalName = name || 'Portal Cobaltax';
  document.title = state.portalName;
  const brandEl = document.getElementById('sidebar-title');
  if (brandEl) brandEl.textContent = state.portalName;
  const loginTitle = document.getElementById('login-portal-name');
  if (loginTitle) loginTitle.textContent = state.portalName;
}

// ---- Status bar ----
function setStatus(msg) {
  document.getElementById('status-bar').textContent = msg;
}

// ---- Auth / Login ----
function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('portal').classList.add('hidden');
  document.getElementById('login-pass').value = '';
  document.getElementById('login-error').classList.add('hidden');
  connectSSE(false);
}

function showPortal() {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('portal').classList.remove('hidden');
}

document.getElementById('login-btn').addEventListener('click', doLogin);
document.getElementById('login-pass').addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});
document.getElementById('login-user').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('login-pass').focus();
});

async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('login-btn');
  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Signing in…';
  try {
    const res = await api('POST', '/api/auth/login', { username, password });
    state.user = res.user;
    state.isAdmin = res.is_admin;
    state.permissions = res.permissions || {};
    onAuthenticated();
  } catch (e) {
    errEl.textContent = e.message || 'Invalid credentials';
    errEl.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Login';
  }
}

async function doLogout() {
  await api('POST', '/api/auth/logout').catch(() => {});
  state.user = null;
  state.isAdmin = false;
  state.permissions = {};
  state.currentModule = null;
  clearTimeout(_autoRefreshTimer);
  showLogin();
}

document.getElementById('logout-btn').addEventListener('click', doLogout);

// ---- After login ----
function onAuthenticated() {
  document.getElementById('sidebar-username').textContent = state.user;
  document.getElementById('lang-select').value = state.lang;

  // Audit button for admins in topbar
  const topbarRight = document.querySelector('.topbar-right');
  let auditBtn = document.getElementById('audit-btn');
  if (state.isAdmin && !auditBtn) {
    auditBtn = document.createElement('button');
    auditBtn.id = 'audit-btn';
    auditBtn.className = 'btn btn-sm';
    auditBtn.textContent = '📋 Audit';
    auditBtn.addEventListener('click', openAudit);
    topbarRight.prepend(auditBtn);
  } else if (auditBtn) {
    auditBtn.classList.toggle('hidden', !state.isAdmin);
  }

  document.getElementById('add-server-btn').style.display = state.isAdmin ? '' : 'none';
  document.querySelectorAll('.ws-admin-only').forEach(el => {
    if (state.isAdmin) el.classList.remove('hidden');
  });
  if (window._refreshConfigImportCard) _refreshConfigImportCard();

  buildModuleNav();
  showPortal();
  connectSSE(true);
  scheduleAutoRefresh();
  loadPrinterHealth();
  loadHealthApps();
  loadHealthBackups();
  // Warm /api/servers cache so it's available offline; also used as SSE fallback
  fetch('/api/servers').then(r => r.ok ? r.json() : null).then(servers => {
    if (!servers) return;
    servers.forEach(s => {
      if (!state.servers[s.ip] || state.servers[s.ip]._checking) {
        state.servers[s.ip] = { ...s, _checking: false };
      }
    });
    renderServers();
  }).catch(() => {});
}

// ---- Module navigation ----
const _MODULE_ICONS = { health: '🖥', apps: '📦', printers: '🖨', support: '🎫', vpn: '🔒', wiki: '📚', ai: '🤖', energy: '⚡', workstations: '💻', settings: '⚙️' };
const _MODULE_I18N  = { health: 'module_health', apps: 'module_apps', printers: 'module_printers', support: 'module_support', vpn: 'module_vpn', wiki: 'module_wiki', ai: 'module_ai', energy: 'module_energy', workstations: 'module_workstations', settings: 'module_settings' };

function buildModuleNav() {
  const nav = document.getElementById('module-nav');
  nav.innerHTML = '';

  const order = ['health', 'apps', 'printers', 'support', 'vpn', 'wiki', 'ai', 'energy', 'workstations'];
  for (const id of order) {
    if (!state.permissions[id]) continue;
    nav.appendChild(_makeNavItem(id));
  }

  if (state.isAdmin) {
    nav.appendChild(_makeNavItem('settings'));
  }

  const first = nav.querySelector('.nav-item');
  if (first) switchModule(first.dataset.module);
}

function _makeNavItem(id) {
  const icon = _MODULE_ICONS[id] || '📁';
  const label = t(_MODULE_I18N[id]) || id;
  const el = document.createElement('div');
  el.className = 'nav-item';
  el.dataset.module = id;
  el.innerHTML = `<span class="nav-icon">${icon}</span><span class="nav-label">${escHtml(label)}</span>`;
  el.addEventListener('click', () => switchModule(id));
  return el;
}

function switchModule(id) {
  document.querySelectorAll('.module').forEach(m => m.classList.add('hidden'));
  const target = document.getElementById(`module-${id}`);
  if (target) target.classList.remove('hidden');

  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.toggle('active', n.dataset.module === id);
  });

  const pageTitleEl = document.getElementById('page-title');
  if (pageTitleEl) pageTitleEl.textContent = t(_MODULE_I18N[id]) || id;

  state.currentModule = id;
  if (id === 'health')   { loadPrinterHealth(); loadHealthApps(); loadHealthBackups(); }
  if (id === 'settings') loadSettings();
  if (id === 'printers') loadPrinters();
  if (id === 'apps')     loadApps();
  if (id === 'support')  loadSupport();
  if (id === 'vpn')      loadVpn();
  if (id === 'wiki')     loadWiki();
  if (id === 'ai')           initAiChat();
  if (id === 'energy')       loadEnergy();
  if (id === 'workstations') loadWorkstations();
}

// ---- Printers ----
let _printers = [];
let _printerEditIdx = null;
let _printerStatus = {};   // { ip: true|false|null }  null = checking

async function loadPrinters() {
  try {
    _printers = await api('GET', '/api/printers');
    // Mark all as checking, render immediately, then fetch ping results
    _printers.forEach(p => { _printerStatus[p.ip] = null; });
    renderPrinters();
    _refreshPrinterStatus();
  } catch (e) {
    toast(`Printers load failed: ${e.message}`, 'err');
  }
}

async function _refreshPrinterStatus() {
  try {
    _printerStatus = await api('GET', '/api/printers/ping');
    renderPrinters();
  } catch (e) {
    toast(`Printer ping failed: ${e.message}`, 'err');
  }
}

function renderPrinters() {
  const tbody = document.getElementById('printers-body');
  const empty = document.getElementById('printers-empty');
  const toolbar = document.getElementById('printers-toolbar');

  toolbar.innerHTML = '';
  // Refresh status button
  const refreshBtn = document.createElement('button');
  refreshBtn.className = 'btn btn-sm';
  refreshBtn.textContent = t('printer_refresh_status');
  refreshBtn.addEventListener('click', () => {
    _printers.forEach(p => { _printerStatus[p.ip] = null; });
    renderPrinters();
    _refreshPrinterStatus();
  });
  toolbar.appendChild(refreshBtn);
  if (state.isAdmin) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-primary';
    btn.textContent = t('printer_add') || 'Add Printer';
    btn.addEventListener('click', () => openPrinterModal(null));
    toolbar.appendChild(btn);
  }

  tbody.innerHTML = '';
  if (!_printers.length) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  _printers.forEach((p, i) => {
    const tr = document.createElement('tr');
    const viewLink = `<a href="http://${escHtml(p.ip)}/" target="_blank" class="link-subtle">${escHtml(p.ip)}</a>`;
    const ipc = encodeURIComponent(p.ip);

    // Status cell
    const online = _printerStatus[p.ip];
    const statusCls = online === null ? 'checking' : (online ? 'online' : 'offline');
    const statusTxt = online === null ? 'Checking…' : (online ? 'Online' : 'Offline');
    const statusCell = `<span class="printer-status ${statusCls}"><span class="status-dot ${statusCls}"></span>${statusTxt}</span>`;

    const exeBtn = p.link
      ? `<a href="/${escHtml(p.link)}" class="btn btn-sm btn-install" download>⬇ EXE</a>`
      : '';
    const ps1Btns = `<span class="ps1-btns">
        <a href="/api/printers/${ipc}/install.ps1?os_slot=win11" class="btn btn-sm btn-install" download>⬇ Win11</a>
        <a href="/api/printers/${ipc}/install.ps1?os_slot=win10_64" class="btn btn-sm btn-install" download>⬇ W10 64</a>
        <a href="/api/printers/${ipc}/install.ps1?os_slot=win10_32" class="btn btn-sm btn-install" download>⬇ W10 32</a>
      </span>`;
    const adminBtns = state.isAdmin ? `
      <button class="btn btn-sm" onclick="openPrinterModal(${i})">${escHtml(t('printer_edit') || 'Edit')}</button>
      <button class="btn btn-sm btn-danger" onclick="deletePrinter(${i})">${escHtml(t('printer_delete') || 'Delete')}</button>` : '';
    tr.innerHTML = `
      <td>${escHtml(p.name)}</td>
      <td>${escHtml(p.location || '')}</td>
      <td>${viewLink}</td>
      <td>${statusCell}</td>
      <td class="printer-actions">${exeBtn}${ps1Btns}${adminBtns}</td>`;
    tbody.appendChild(tr);
  });
}

const _OS_SLOTS = { win11: 'Windows 11', win10_64: 'Windows 10 (64-bit)', win10_32: 'Windows 10 (32-bit)' };

function _resetSlotInfo(text) {
  for (const slot of Object.keys(_OS_SLOTS)) {
    const el = document.getElementById(`pm-slot-info-${slot}`);
    if (el) el.textContent = text;
  }
}

function openPrinterModal(idx) {
  _printerEditIdx = idx;
  const p = idx !== null ? _printers[idx] : {};
  document.getElementById('printer-modal-title').textContent = idx !== null ? (t('printer_edit') || 'Edit') : (t('printer_add') || 'Add');
  document.getElementById('pm-name').value = p.name || '';
  document.getElementById('pm-location').value = p.location || '';
  document.getElementById('pm-ip').value = p.ip || '';
  document.getElementById('pm-driver').value = p.link || '';
  document.getElementById('pm-wdriver').value = p.driver_name || '';
  document.getElementById('pm-inf-status').textContent = '';
  if (p.ip) {
    _resetSlotInfo('Checking…');
    api('GET', `/api/printers/${encodeURIComponent(p.ip)}/driver/status`).then(s => {
      for (const [slot, info] of Object.entries(s.slots)) {
        const el = document.getElementById(`pm-slot-info-${slot}`);
        if (el) el.textContent = info.has_driver ? `✓ ${info.files.length} file(s)` : 'No driver uploaded';
      }
    }).catch(() => _resetSlotInfo('No driver uploaded'));
  } else {
    _resetSlotInfo('Save printer first, then upload driver');
  }
  document.getElementById('printer-modal').classList.remove('hidden');
}

function closePrinterModal() {
  document.getElementById('printer-modal').classList.add('hidden');
  _printerEditIdx = null;
}

async function savePrinter() {
  const p = {
    name: document.getElementById('pm-name').value.trim(),
    location: document.getElementById('pm-location').value.trim(),
    ip: document.getElementById('pm-ip').value.trim(),
    link: document.getElementById('pm-driver').value.trim(),
    driver_name: document.getElementById('pm-wdriver').value.trim(),
  };
  if (!p.name || !p.ip) { toast('Name and IP are required', 'err'); return; }
  if (_printerEditIdx !== null) {
    _printers[_printerEditIdx] = p;
  } else {
    _printers.push(p);
  }
  try {
    await api('PUT', '/api/printers', _printers);
    closePrinterModal();
    renderPrinters();
  } catch (e) {
    toast(`Save failed: ${e.message}`, 'err');
  }
}

async function deletePrinter(idx) {
  if (!confirm(t('printer_confirm_delete') || 'Delete this printer?')) return;
  _printers.splice(idx, 1);
  try {
    await api('PUT', '/api/printers', _printers);
    renderPrinters();
  } catch (e) {
    toast(`Delete failed: ${e.message}`, 'err');
  }
}

document.getElementById('printer-modal-save').addEventListener('click', savePrinter);
document.getElementById('printer-modal-cancel').addEventListener('click', closePrinterModal);
document.getElementById('printer-modal-close').addEventListener('click', closePrinterModal);

// ── Server CRUD ──────────────────────────────────────────────────────────────
let _serverEditIp = null; // null = add, string = edit

function openServerModal(ip) {
  _serverEditIp = ip || null;
  const s = ip ? state.servers[ip] || {} : {};
  document.getElementById('server-modal-title').textContent = ip ? 'Edit server' : 'Add server';
  document.getElementById('sm-name').value        = s.name        || '';
  document.getElementById('sm-ip').value          = s.ip          || '';
  document.getElementById('sm-ip').disabled       = !!ip;
  document.getElementById('sm-os-type').value     = s.os_type     || 'linux';
  document.getElementById('sm-subnet').value      = s.subnet      || '';
  document.getElementById('sm-parent').value      = s.parent      || '';
  document.getElementById('sm-web-url').value     = s.web_url     || '';
  document.getElementById('sm-ssh-user').value    = s.ssh_user    || '';
  document.getElementById('sm-ssh-password').value = '';
  document.getElementById('sm-ssh-port').value    = s.ssh_port    || 22;
  document.getElementById('sm-ssh-key').value     = s.ssh_key_path || '';
  document.getElementById('sm-watts-idle').value  = s.watts_idle  || 0;
  document.getElementById('sm-watts-max').value   = s.watts_max   || 0;
  document.getElementById('server-modal').classList.remove('hidden');
}

function closeServerModal() {
  document.getElementById('server-modal').classList.add('hidden');
  _serverEditIp = null;
}

async function saveServer() {
  const body = {
    name:          document.getElementById('sm-name').value.trim(),
    ip:            (_serverEditIp || document.getElementById('sm-ip').value.trim()),
    os_type:       document.getElementById('sm-os-type').value,
    subnet:        document.getElementById('sm-subnet').value.trim(),
    parent:        document.getElementById('sm-parent').value.trim(),
    web_url:       document.getElementById('sm-web-url').value.trim(),
    ssh_user:      document.getElementById('sm-ssh-user').value.trim(),
    ssh_password:  document.getElementById('sm-ssh-password').value,
    ssh_port:      parseInt(document.getElementById('sm-ssh-port').value) || 22,
    ssh_key_path:  document.getElementById('sm-ssh-key').value.trim(),
    watts_idle:    parseInt(document.getElementById('sm-watts-idle').value) || 0,
    watts_max:     parseInt(document.getElementById('sm-watts-max').value) || 0,
  };
  if (!body.name || !body.ip) { toast('Name and IP are required', 'err'); return; }
  try {
    if (_serverEditIp) {
      await api('PUT', `/api/servers/${encodeURIComponent(_serverEditIp)}`, body);
      toast('Server updated');
    } else {
      await api('POST', '/api/servers', body);
      toast('Server added');
    }
    closeServerModal();
    renderServers();
  } catch (e) {
    toast(`Save failed: ${e.message}`, 'err');
  }
}

async function deleteServer(ip) {
  if (!confirm(`Delete server ${ip}?`)) return;
  try {
    await api('DELETE', `/api/servers/${encodeURIComponent(ip)}`);
    delete state.servers[ip];
    toast('Server deleted');
    renderServers();
  } catch (e) {
    toast(`Delete failed: ${e.message}`, 'err');
  }
}

document.getElementById('server-modal-save').addEventListener('click', saveServer);
document.getElementById('server-modal-cancel').addEventListener('click', closeServerModal);
document.getElementById('server-modal-close').addEventListener('click', closeServerModal);
document.getElementById('add-server-btn').addEventListener('click', () => openServerModal(null));

for (const slot of Object.keys(_OS_SLOTS)) {
  const input = document.getElementById(`pm-inf-${slot}`);
  if (!input) continue;
  input.addEventListener('change', async function () {
    if (!this.files.length) return;
    const ip = document.getElementById('pm-ip').value.trim();
    if (!ip) { toast('Enter the printer IP first', 'err'); this.value = ''; return; }
    const infoEl = document.getElementById(`pm-slot-info-${slot}`);
    const statusEl = document.getElementById('pm-inf-status');
    infoEl.textContent = `Uploading ${this.files.length} file(s)…`;
    try {
      const fd = new FormData();
      for (const f of this.files) fd.append('files', f);
      const res = await fetch(`/api/printers/${encodeURIComponent(ip)}/driver?os_slot=${slot}`, { method: 'POST', body: fd });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || res.statusText); }
      const data = await res.json();
      infoEl.textContent = `✓ ${data.files.length} file(s)`;
      statusEl.textContent = `${_OS_SLOTS[slot]}: uploaded ${data.files.length} file(s)`;
      toast(`${_OS_SLOTS[slot]} driver uploaded`, 'ok');
    } catch (e) {
      infoEl.textContent = 'Upload failed';
      statusEl.textContent = `Upload failed: ${e.message}`;
      toast(`Driver upload failed: ${e.message}`, 'err');
    }
    this.value = '';
  });
}

document.getElementById('pm-file-input').addEventListener('change', async function () {
  const file = this.files[0];
  if (!file) return;
  const statusEl = document.getElementById('pm-upload-status');
  statusEl.textContent = `Uploading ${file.name}…`;
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/printers/upload', { method: 'POST', body: fd });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || res.statusText); }
    const data = await res.json();
    document.getElementById('pm-driver').value = data.link;
    statusEl.textContent = `Uploaded: ${data.filename}`;
  } catch (e) {
    statusEl.textContent = `Upload failed: ${e.message}`;
    toast(`Upload failed: ${e.message}`, 'err');
  }
  this.value = '';
});

// ---- Sidebar collapse ----
document.getElementById('sidebar-toggle').addEventListener('click', () => {
  document.getElementById('portal').classList.toggle('sidebar-collapsed');
});

// ---- Mobile menu ----
document.getElementById('mobile-menu-btn').addEventListener('click', () => {
  document.getElementById('portal').classList.toggle('menu-open');
});

// ---- Language ----
document.getElementById('lang-select').addEventListener('change', async e => {
  await loadTranslations(e.target.value);
  applyI18n();
  buildModuleNav();
  renderServers();
});

// ---- SSE ----
function connectSSE(connect) {
  if (state.sseSource) {
    state.sseSource.close();
    state.sseSource = null;
  }
  if (!connect) return;

  const es = new EventSource('/api/servers/stream');
  state.sseSource = es;

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'snapshot') {
      msg.servers.forEach(s => { state.servers[s.ip] = { ...s, _checking: false }; });
      renderServers();
    } else if (msg.type === 'status') {
      const s = msg.server;
      state.servers[s.ip] = { ...(state.servers[s.ip] || {}), ...s, _checking: false };
      updateCard(s.ip);
    } else if (msg.type === 'action_result') {
      toast(msg.message || '', msg.ok ? 'ok' : 'err', 4000);
      setStatus(msg.message || '');
      if (msg.action === 'restart' && msg.ok) {
        setTimeout(() => refreshServer(msg.ip), 8000);
      }
    }
  };

  es.onerror = () => {
    if (!state.user) return;
    // When offline, fall back to cached /api/servers immediately
    if (!navigator.onLine) {
      _loadServersFromCache();
      setTimeout(() => connectSSE(true), 30000);   // back off — no point hammering while offline
    } else {
      setTimeout(() => connectSSE(true), 5000);
    }
  };
}

// Populate server cards from cached REST response (offline fallback)
function _loadServersFromCache() {
  fetch('/api/servers').then(r => r.ok ? r.json() : null).then(servers => {
    if (!servers) return;
    servers.forEach(s => {
      state.servers[s.ip] = { ...(state.servers[s.ip] || {}), ...s, _checking: false };
    });
    renderServers();
    setStatus('Offline — showing last cached status');
  }).catch(() => {});
}

// ---- Subnet helpers ----
function _subnetLabel(subnet) {
  const key = `subnet_${subnet}`;
  const val = t(key);
  return val !== key ? val : subnet;
}
const _SUBNET_ORDER = ['cobaltax_main', 'cobaltax_tienda'];
const _NET_TYPES = new Set(['router', 'ap', 'switch', 'network_device']);

function _detectSubnet(ip) {
  if (!ip) return 'unknown';
  const p = ip.split('.');
  if (p[0] === '192' && p[1] === '168') {
    if (p[2] === '23') return 'cobaltax_main';
    if (p[2] === '9')  return 'cobaltax_tienda';
  }
  return 'unknown';
}

// ---- Render servers ----
function renderServers() {
  const grid = document.getElementById('servers-grid');
  grid.innerHTML = '';
  const servers = Object.values(state.servers);

  // Build children map for server hierarchy
  const childrenMap = {};
  servers.forEach(s => {
    if (s.parent) (childrenMap[s.parent] = childrenMap[s.parent] || []).push(s.ip);
  });
  const childSet = new Set(servers.filter(s => s.parent).map(s => s.ip));

  // Group by subnet
  const bySubnet = {};
  servers.forEach(s => {
    const key = s.subnet || _detectSubnet(s.ip);
    (bySubnet[key] = bySubnet[key] || []).push(s);
  });

  const subnetKeys = _SUBNET_ORDER.filter(k => bySubnet[k])
    .concat(Object.keys(bySubnet).filter(k => !_SUBNET_ORDER.includes(k)));

  subnetKeys.forEach(subnet => {
    const subnetServers = bySubnet[subnet];
    const section = document.createElement('div');
    section.className = 'subnet-section';

    // Subnet header
    const onlineCount = subnetServers.filter(s => statusClass(s) === 'online').length;
    const header = document.createElement('div');
    header.className = 'subnet-header';
    header.innerHTML = `<span class="subnet-label">${escHtml(_subnetLabel(subnet))}</span>`
      + `<span class="subnet-count">${onlineCount}/${subnetServers.length} online</span>`;
    section.appendChild(header);

    // Split: network devices vs servers
    const netDevs = subnetServers.filter(s => _NET_TYPES.has(s.os_type));
    const srvs    = subnetServers.filter(s => !_NET_TYPES.has(s.os_type));

    function _makeGroup(label, items, ordered) {
      const group = document.createElement('div');
      group.className = 'subnet-group';
      const lbl = document.createElement('div');
      lbl.className = 'subnet-group-label';
      lbl.textContent = label;
      group.appendChild(lbl);
      const cardGrid = document.createElement('div');
      cardGrid.className = 'subnet-cards-grid';
      ordered.forEach(s => cardGrid.appendChild(buildCard(s, !!childrenMap[s.ip], childSet.has(s.ip))));
      group.appendChild(cardGrid);
      section.appendChild(group);
    }

    if (netDevs.length) _makeGroup(t('health_network_devices'), netDevs, netDevs);

    if (srvs.length) {
      // Order: parents → their children → orphans → stray children
      const parents = srvs.filter(s => childrenMap[s.ip] && !s.parent);
      const orphans  = srvs.filter(s => !childrenMap[s.ip] && !s.parent);
      const ordered  = [];
      parents.forEach(p => {
        ordered.push(p);
        (childrenMap[p.ip] || []).forEach(cip => {
          const c = state.servers[cip];
          if (c && srvs.includes(c)) ordered.push(c);
        });
      });
      orphans.forEach(s => ordered.push(s));
      srvs.filter(s => s.parent && !ordered.includes(s)).forEach(s => ordered.push(s));
      _makeGroup(t('health_servers'), srvs, ordered);
    }

    grid.appendChild(section);
  });

  setStatus(t('status_refresh_completed') || 'Status updated');
}

// ---- Build server card ----
function buildCard(server, isParent, isChild) {
  const div = document.createElement('div');
  const isNetDev = _NET_TYPES.has(server.os_type);
  div.className = 'server-card'
    + (isParent ? ' is-parent' : '')
    + (isChild  ? ' is-child'  : '')
    + (isNetDev ? ' is-netdev' : '');
  div.id = `card-${server.ip.replace(/\./g, '-')}`;
  div.innerHTML = cardHTML(server);
  bindCardActions(div, server);
  return div;
}

function statusClass(s) {
  if (!s || s._checking) return 'checking';
  // Network devices are online if ping succeeds (no SSH check)
  if (_NET_TYPES.has(s.os_type)) return s.ping ? 'online' : 'offline';
  if (s.online || s.ssh) return 'online';
  if (s.ping && !s.ssh) return 'ssh-closed';
  return 'offline';
}

function osBadge(osType) {
  const map = { linux: '🐧 linux', windows: '🪟 windows', esxi: '🖥 esxi',
                synology: '🗄 synology', router: '🔀 router', ap: '📶 AP', switch: '🔌 switch' };
  return map[osType] || (osType || 'linux');
}

function statusLabel(s) {
  const cls = statusClass(s);
  if (cls === 'checking')   return t('checking')        || 'Checking…';
  if (cls === 'online')     return t('online')           || 'Online';
  if (cls === 'ssh-closed') return t('ssh_port_closed')  || 'SSH Port Closed';
  return t('offline') || 'Offline';
}

function resourcesText(s) {
  if (!s || !s.resources) return '';
  const r = s.resources;
  if (r.error) return '';
  const parts = [];
  if (r.cpu_percent != null) parts.push(`CPU ${r.cpu_percent}%`);
  if (r.mem_percent != null) parts.push(`RAM ${r.mem_percent}%`);
  if (r.volumes && r.volumes.length) {
    r.volumes.forEach(v => parts.push(`${v.mount} ${v.free} free (${v.percent}%)`));
  } else if (r.disk_percent != null) {
    parts.push(`Disk ${r.disk_percent}%`);
  }
  return parts.join('  ·  ');
}

function cardHTML(s) {
  const ip       = s.ip;
  const sc       = statusClass(s);
  const lc       = s.last_check || s.last_checked || '';
  const res      = resourcesText(s);
  const dep      = depLine(s);
  const online   = sc === 'online';
  const isNetDev = _NET_TYPES.has(s.os_type);
  const canAction = !isNetDev && (state.isAdmin || state.permissions.health === 'admin');

  return `
    <div class="card-header">
      <span class="status-dot ${sc}"></span>
      <div style="flex:1">
        <div class="card-name">${escHtml(s.name || s.ip)}</div>
        <div class="card-ip">${escHtml(s.ip)}</div>
      </div>
      <span class="os-badge">${escHtml(osBadge(s.os_type))}</span>
    </div>
    <div class="card-status ${sc}">${statusLabel(s)}${s.watts != null && s.watts > 0 ? `<span class="energy-badge">⚡${Math.round(s.watts)}W</span>` : ''}</div>
    ${!isNetDev && res ? `<div class="card-resources">${escHtml(res)}</div>` : ''}
    ${dep ? `<div class="card-dep">${escHtml(dep)}</div>` : ''}
    ${!isNetDev && s.resources?.uptime ? `<div class="card-meta">Up: ${escHtml(s.resources.uptime)}</div>` : ''}
    ${lc ? `<div class="card-meta">Last check: ${escHtml(String(lc))}</div>` : ''}
    ${isNetDev ? `
    <div class="card-actions">
      <a class="btn" href="${escHtml(s.web_url || 'http://' + ip + '/')}" target="_blank" rel="noopener">&#x1F310; Open Web UI</a>
    </div>` : ''}
    ${canAction ? `
    <div class="card-actions">
      <button class="btn btn-danger restart-btn" data-ip="${ip}" ${online ? '' : 'disabled'}>&#x1F504; Restart</button>
      <button class="btn open-terminal-btn" data-ip="${ip}" ${online ? '' : 'disabled'}>&#x1F4BB; Terminal</button>
      <button class="btn test-sudo-btn" data-ip="${ip}">&#x1F511; Sudo</button>
      <button class="btn edit-server-btn" data-ip="${ip}" title="Edit server">✏️</button>
      <button class="btn btn-danger delete-server-btn" data-ip="${ip}" title="Delete server">🗑️</button>
    </div>` : ''}`;
}

function depLine(s) {
  const parentSrv  = s.parent && state.servers[s.parent];
  const childSrvs  = Object.values(state.servers).filter(c => c.parent === s.ip);
  const parts = [];
  if (parentSrv) parts.push(`Parent: ${parentSrv.name || s.parent}`);
  if (childSrvs.length) {
    const up = childSrvs.filter(c => statusClass(c) === 'online').length;
    parts.push(`Children: ${childSrvs.map(c => c.name || c.ip).join(', ')} [${up}/${childSrvs.length} up]`);
  }
  return parts.join(' | ');
}

function bindCardActions(card, server) {
  card.querySelector('.restart-btn')?.addEventListener('click',       () => confirmRestart(server));
  card.querySelector('.open-terminal-btn')?.addEventListener('click', () => openSSHTerminal(server));
  card.querySelector('.test-sudo-btn')?.addEventListener('click',     () => testSudo(server));
  card.querySelector('.edit-server-btn')?.addEventListener('click',   () => openServerModal(server.ip));
  card.querySelector('.delete-server-btn')?.addEventListener('click', () => deleteServer(server.ip));
}

function updateCard(ip) {
  const s = state.servers[ip];
  if (!s) return;
  const existing = document.getElementById(`card-${ip.replace(/\./g, '-')}`);
  if (!existing) { renderServers(); return; }
  existing.innerHTML = cardHTML(s);
  bindCardActions(existing, s);
  if (s.parent) updateCard(s.parent);
}

// ---- Server actions ----
async function refreshServer(ip) {
  await api('POST', `/api/servers/${ip}/refresh`).catch(e => toast(e.message, 'err'));
}

async function refreshAll() {
  setStatus('Refreshing…');
  await Promise.all(Object.keys(state.servers).map(ip => refreshServer(ip))).catch(() => {});
}

async function confirmRestart(server) {
  const pw = await requirePasswordConfirm(
    'Confirm restart',
    `You are about to restart ${server.name} (${server.ip}). Enter your password to proceed.`
  );
  if (pw === null) return;
  doRestart(server, pw);
}

async function doRestart(server, confirmPassword) {
  setStatus(`Restarting ${server.name}…`);
  try {
    await api('POST', `/api/servers/${server.ip}/restart`, { confirm_password: confirmPassword });
    toast(`Restart initiated for ${server.name}`, 'info');
  } catch (e) {
    toast(`Restart failed: ${e.message}`, 'err');
  }
}

// ---- SSH Terminal ----
let _sshTerm = null;
let _sshWs   = null;
let _sshFit  = null;

function openSSHTerminal(server) {
  document.getElementById('ssh-modal-title').textContent = `${server.name} (${server.ip})`;
  const statusEl    = document.getElementById('ssh-conn-status');
  const containerEl = document.getElementById('ssh-terminal-container');
  statusEl.textContent    = 'Connecting…';
  containerEl.innerHTML   = '';

  if (_sshTerm) { _sshTerm.dispose(); _sshTerm = null; }
  if (_sshWs)   { _sshWs.close();    _sshWs   = null; }

  document.getElementById('ssh-overlay').classList.remove('hidden');

  _sshTerm = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {
      background: '#0d1117',
      foreground: '#e2e4ef',
      cursor: '#4f8ef7',
      selectionBackground: '#2e3248',
    },
    scrollback: 2000,
  });

  _sshFit = new FitAddon.FitAddon();
  _sshTerm.loadAddon(_sshFit);
  _sshTerm.open(containerEl);
  _sshFit.fit();

  const { cols, rows } = _sshTerm;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  _sshWs = new WebSocket(`${proto}//${location.host}/ws/ssh/${server.ip}?rows=${rows}&cols=${cols}`);

  _sshWs.onopen = () => {
    statusEl.textContent = 'Connected';
    statusEl.style.color = 'var(--success)';
    _sshTerm.focus();
  };
  _sshWs.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'data') _sshTerm.write(msg.data);
  };
  _sshWs.onclose = () => {
    statusEl.textContent = 'Disconnected';
    statusEl.style.color = 'var(--text-dim)';
    _sshTerm.write('\r\n\x1b[33m[Connection closed]\x1b[0m\r\n');
  };
  _sshWs.onerror = () => {
    statusEl.textContent = 'Connection error';
    statusEl.style.color = 'var(--danger)';
  };

  _sshTerm.onData(data => {
    if (_sshWs && _sshWs.readyState === WebSocket.OPEN)
      _sshWs.send(JSON.stringify({ type: 'data', data }));
  });
  _sshTerm.onResize(({ cols, rows }) => {
    if (_sshWs && _sshWs.readyState === WebSocket.OPEN)
      _sshWs.send(JSON.stringify({ type: 'resize', cols, rows }));
  });

  const ro = new ResizeObserver(() => { if (_sshFit) _sshFit.fit(); });
  ro.observe(containerEl);
  _sshTerm._ro = ro;
}

function closeSSHTerminal() {
  if (_sshTerm) {
    if (_sshTerm._ro) _sshTerm._ro.disconnect();
    _sshTerm.dispose();
    _sshTerm = null;
  }
  if (_sshWs) { _sshWs.close(); _sshWs = null; }
  _sshFit = null;
  document.getElementById('ssh-overlay').classList.add('hidden');
  document.getElementById('ssh-terminal-container').innerHTML = '';
}

document.getElementById('ssh-close-btn').addEventListener('click', closeSSHTerminal);

async function testSudo(server) {
  setStatus(`Testing sudo on ${server.name}…`);
  try {
    await api('POST', `/api/servers/${server.ip}/test-sudo`);
    toast(`Sudo test sent to ${server.name}`, 'info');
  } catch (e) {
    toast(`Sudo test error: ${e.message}`, 'err');
  }
}

// ---- Auto-refresh ----
let _autoRefreshTimer = null;

function scheduleAutoRefresh() {
  clearTimeout(_autoRefreshTimer);
  if (state.autoRefresh && state.user) {
    _autoRefreshTimer = setTimeout(() => {
      refreshAll();
      scheduleAutoRefresh();
    }, state.refreshInterval * 1000);
  }
}

document.getElementById('refresh-btn').addEventListener('click', () => {
  refreshAll();
  scheduleAutoRefresh();
});

document.getElementById('auto-refresh-cb').addEventListener('change', e => {
  state.autoRefresh = e.target.checked;
  scheduleAutoRefresh();
  setStatus(state.autoRefresh ? t('auto_refresh_enabled') : t('auto_refresh_disabled'));
});

// ---- Settings ----
async function loadSettings() {
  try {
    const data = await api('GET', '/api/settings');
    document.getElementById('setting-portal-name').value  = data.portal_name        || '';
    document.getElementById('setting-admin-group').value  = data.portal_admin_group || '';
    document.getElementById('setting-lang').value         = data.default_language   || 'en';
    renderModuleSettingsCards(data.modules || []);
  } catch (e) {
    toast(`Settings load failed: ${e.message}`, 'err');
  }
}

function renderModuleSettingsCards(modules) {
  const container = document.getElementById('module-settings-cards');
  container.innerHTML = '';
  for (const mod of modules) {
    const card = document.createElement('div');
    card.className = 'settings-card';
    card.innerHTML = `
      <h3>${escHtml(mod.icon || '')} ${escHtml(t(_MODULE_I18N[mod.id]) || mod.id)}</h3>
      <div class="form-group">
        <label>Enabled</label>
        <label class="toggle-label">
          <input type="checkbox" data-mod="${escHtml(mod.id)}" data-field="enabled" ${mod.enabled ? 'checked' : ''} />
          <span>${mod.enabled ? 'Yes' : 'No'}</span>
        </label>
      </div>
      <div class="form-group">
        <label>View group (AD)</label>
        <input type="text" data-mod="${escHtml(mod.id)}" data-field="view_group"  value="${escHtml(mod.view_group  || '')}" />
      </div>
      <div class="form-group">
        <label>Admin group (AD)</label>
        <input type="text" data-mod="${escHtml(mod.id)}" data-field="admin_group" value="${escHtml(mod.admin_group || '')}" />
      </div>`;
    container.appendChild(card);
  }
}

document.getElementById('settings-save-btn').addEventListener('click', async () => {
  const statusEl = document.getElementById('settings-status');
  statusEl.textContent = 'Saving…';
  try {
    const data = {
      portal_name:        document.getElementById('setting-portal-name').value.trim(),
      portal_admin_group: document.getElementById('setting-admin-group').value.trim(),
      default_language:   document.getElementById('setting-lang').value,
      modules: [],
    };

    const modIds = new Set();
    document.querySelectorAll('[data-mod]').forEach(el => modIds.add(el.dataset.mod));
    for (const mid of modIds) {
      const mod = { id: mid };
      const cb = document.querySelector(`[data-mod="${mid}"][data-field="enabled"]`);
      const vg = document.querySelector(`[data-mod="${mid}"][data-field="view_group"]`);
      const ag = document.querySelector(`[data-mod="${mid}"][data-field="admin_group"]`);
      if (cb) mod.enabled    = cb.checked;
      if (vg) mod.view_group  = vg.value.trim();
      if (ag) mod.admin_group = ag.value.trim();
      data.modules.push(mod);
    }

    await api('PUT', '/api/settings', data);
    applyPortalName(data.portal_name);
    statusEl.textContent = '✔ Saved';
    toast('Settings saved', 'ok');
    setTimeout(() => { statusEl.textContent = ''; }, 3000);
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
    toast(`Save failed: ${e.message}`, 'err');
  }
});

// ---- Config Export / Import ----

(function () {
  const card     = document.getElementById('config-export-import-card');
  const exportBtn  = document.getElementById('config-export-btn');
  const fileInput  = document.getElementById('config-import-file');
  const importBtn  = document.getElementById('config-import-btn');
  const fileLabel  = document.getElementById('config-import-filename');
  const resultPre  = document.getElementById('config-import-result');

  // Show card only for admins (called after login)
  window._refreshConfigImportCard = function () {
    if (card) card.classList.toggle('hidden', !state.isAdmin);
  };

  fileInput.addEventListener('change', () => {
    const f = fileInput.files[0];
    fileLabel.textContent = f ? f.name : '';
    importBtn.disabled = !f;
    resultPre.classList.add('hidden');
  });

  exportBtn.addEventListener('click', async () => {
    exportBtn.disabled = true;
    exportBtn.textContent = '⬇ Exporting…';
    try {
      const res = await fetch('/api/admin/config/export');
      if (res.status === 401) { showLogin(); throw new Error('Unauthenticated'); }
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      const date = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `cobaltax-config-${date}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(`Export failed: ${e.message}`, 'err');
    } finally {
      exportBtn.disabled = false;
      exportBtn.textContent = '⬇ Export config';
    }
  });

  importBtn.addEventListener('click', async () => {
    const f = fileInput.files[0];
    if (!f) return;

    const pw = await requirePasswordConfirm(
      'Confirm import',
      'Importing will overwrite servers, settings and users. Enter your password to proceed.'
    );
    if (pw === null) return;

    importBtn.disabled = true;
    importBtn.textContent = 'Importing…';
    resultPre.classList.add('hidden');
    try {
      const text = await f.text();
      const body = JSON.parse(text);
      body.confirm_password = pw;
      const res  = await api('POST', '/api/admin/config/import', body);
      const msg  = `✔ Imported: ${res.imported.servers} server(s), ${res.imported.settings} setting(s), ${res.imported.users} user(s)`;
      resultPre.textContent = msg;
      resultPre.classList.remove('hidden');
      toast(msg, 'ok');
      fileInput.value = '';
      fileLabel.textContent = '';
      importBtn.disabled = true;
    } catch (e) {
      resultPre.textContent = `Error: ${e.message}`;
      resultPre.classList.remove('hidden');
      toast(`Import failed: ${e.message}`, 'err');
      importBtn.disabled = false;
    } finally {
      importBtn.textContent = 'Import';
    }
  });
})();

// ---- Apps module ----
let _appsData = { apps: [], links: [] };
let _editingLinkIdx = -1;

async function loadApps() {
  try {
    _appsData = await api('GET', '/api/apps');
    renderApps();
  } catch (e) {
    toast(`Apps load failed: ${e.message}`, 'err');
  }
}

function _iconEl(icon) {
  if (!icon) return '📦';
  if (icon.startsWith('http') || icon.startsWith('/')) {
    return `<img src="${escHtml(icon)}" class="app-icon-img" alt="" />`;
  }
  return `<span class="app-icon-emoji">${escHtml(icon)}</span>`;
}

function renderApps() {
  const appsGrid  = document.getElementById('apps-grid');
  const linksGrid = document.getElementById('links-grid');
  const linksEmpty = document.getElementById('links-empty');
  const addLinkBtn = document.getElementById('add-link-btn');

  // Show add-link button for admins
  if (addLinkBtn) addLinkBtn.style.display = state.isAdmin ? '' : 'none';

  // --- Software ---
  appsGrid.innerHTML = '';
  for (const app of (_appsData.apps || [])) {
    const card = document.createElement('div');
    card.className = 'app-card';

    let actionHTML = '';
    if (app.url_type === 'external') {
      actionHTML = `<a class="btn btn-primary btn-sm app-dl-btn" href="${escHtml(app.url)}" target="_blank" download>${t('apps_download') || 'Download'}</a>`;
    } else if (app.url_type === 'upload') {
      if (app.url) {
        actionHTML = `<a class="btn btn-primary btn-sm app-dl-btn" href="/${escHtml(app.url)}" download>${t('apps_download') || 'Download'}</a>`;
        if (state.isAdmin) {
          actionHTML += `<label class="btn btn-sm upload-btn" for="app-upload-${escHtml(app.id)}">${t('apps_replace') || 'Replace'}</label>`;
        }
      } else if (state.isAdmin) {
        actionHTML = `<label class="btn btn-primary btn-sm upload-btn" for="app-upload-${escHtml(app.id)}">${t('apps_upload_installer') || 'Upload installer'}</label>`;
      } else {
        actionHTML = `<span class="text-dim" style="font-size:0.75rem">${t('apps_not_available') || 'Not available yet'}</span>`;
      }
      if (state.isAdmin) {
        actionHTML += `<input type="file" id="app-upload-${escHtml(app.id)}" data-appid="${escHtml(app.id)}" accept=".exe,.msi" class="app-file-input" style="display:none" />`;
      }
    }

    card.innerHTML = `
      <div class="app-card-icon">${_iconEl(app.icon)}</div>
      <div class="app-card-label">${escHtml(app.label)}</div>
      <div class="app-card-desc">${escHtml(app.description || '')}</div>
      <div class="app-card-actions">${actionHTML}</div>`;
    appsGrid.appendChild(card);
  }

  // Bind file upload inputs
  appsGrid.querySelectorAll('.app-file-input').forEach(inp => {
    inp.addEventListener('change', async function() {
      const appId = this.dataset.appid;
      const file  = this.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      try {
        const res = await fetch(`/api/apps/${appId}/upload`, { method: 'POST', body: fd });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || res.statusText); }
        toast(`Uploaded: ${file.name}`, 'ok');
        await loadApps();
      } catch (e) {
        toast(`Upload failed: ${e.message}`, 'err');
      }
      this.value = '';
    });
  });

  // --- Links ---
  const links = _appsData.links || [];
  linksGrid.innerHTML = '';
  linksEmpty.classList.toggle('hidden', links.length > 0);

  links.forEach((lnk, idx) => {
    const card = document.createElement('div');
    card.className = 'app-card';
    let adminBtns = '';
    if (state.isAdmin) {
      adminBtns = `
        <button class="btn btn-sm link-edit-btn" data-idx="${idx}">✏️</button>
        <button class="btn btn-sm btn-danger link-del-btn" data-idx="${idx}">🗑</button>`;
    }
    card.innerHTML = `
      <div class="app-card-icon">${_iconEl(lnk.icon || '🔗')}</div>
      <div class="app-card-label">${escHtml(lnk.label)}</div>
      <div class="app-card-desc">${escHtml(lnk.description || '')}</div>
      <div class="app-card-actions">
        <a class="btn btn-primary btn-sm" href="${escHtml(lnk.url)}" target="_blank" rel="noopener">${t('apps_open') || 'Open'}</a>
        ${adminBtns}
      </div>`;
    linksGrid.appendChild(card);
  });

  linksGrid.querySelectorAll('.link-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => openLinkModal(parseInt(btn.dataset.idx)));
  });
  linksGrid.querySelectorAll('.link-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(t('link_confirm_delete') || 'Delete this link?')) return;
      const links = [..._appsData.links];
      links.splice(parseInt(btn.dataset.idx), 1);
      await saveLinks(links);
    });
  });
}

function openLinkModal(idx = -1) {
  _editingLinkIdx = idx;
  const lnk = idx >= 0 ? _appsData.links[idx] : {};
  document.getElementById('link-modal-title').textContent = idx >= 0 ? (t('link_edit') || 'Edit link') : (t('apps_add_link') || 'Add link');
  document.getElementById('lm-label').value = lnk.label || '';
  document.getElementById('lm-url').value   = lnk.url   || '';
  document.getElementById('lm-icon').value  = lnk.icon  || '';
  document.getElementById('lm-desc').value  = lnk.description || '';
  // Reset picker state
  document.getElementById('icon-picker-panel').classList.add('hidden');
  document.getElementById('icon-pick-toggle').textContent = '🎨 Choose…';
  _updateIconPreview(lnk.icon || '🔗');
  if (document.getElementById('icon-picker-panel').children.length) {
    document.querySelectorAll('#icon-picker-panel .icon-opt').forEach(b => {
      b.classList.toggle('active', b.title === (lnk.icon || ''));
    });
  }
  document.getElementById('link-modal').classList.remove('hidden');
}

function closeLinkModal() {
  document.getElementById('link-modal').classList.add('hidden');
}

async function saveLinks(links) {
  try {
    await api('PUT', '/api/apps/links', links);
    _appsData.links = links;
    renderApps();
    toast('Links saved', 'ok');
  } catch (e) {
    toast(`Save failed: ${e.message}`, 'err');
  }
}

document.getElementById('add-link-btn').addEventListener('click', () => openLinkModal(-1));
document.getElementById('link-modal-close').addEventListener('click', closeLinkModal);
document.getElementById('link-modal-cancel').addEventListener('click', closeLinkModal);

// ---- Icon picker ----
const _ICON_LIST = [
  // Web & links
  '🌐','🔗','🌍','📡','📶','🛜',
  // Files & docs
  '📁','📂','📄','📃','📋','📊','📈','📝','🗂','📦','🗃','📑',
  // Communication
  '💬','📧','📨','📩','📤','📥','☎️','📞','📱','📣','📢','💌',
  // Tools & security
  '🔧','🔨','⚙️','🛠','🔑','🗝','🔐','🔒','🔓','✂️',
  // Business & planning
  '💼','🏢','💰','💳','📅','🗓','✅','☑️','📌','📎','🏷',
  // IT & servers
  '🖥','💻','🖨','⌨️','💾','📀','🖱','📟','🖲',
  // Status & alerts
  '⭐','🏠','🚀','🎯','❗','ℹ️','✨','🆕','🔴','🟡','🟢','🔵','⚡','🔥','⚠️',
  // People
  '👤','👥','👩‍💻','👨‍💼',
  // Service favicons via Google S2 (renders the real brand icon)
  // --- Your tools ---
  'https://www.google.com/s2/favicons?sz=64&domain=mantisbt.org',
  'https://www.google.com/s2/favicons?sz=64&domain=synology.com',
  // --- AI ---
  'https://www.google.com/s2/favicons?sz=64&domain=claude.ai',
  'https://www.google.com/s2/favicons?sz=64&domain=chatgpt.com',
  'https://www.google.com/s2/favicons?sz=64&domain=gemini.google.com',
  // --- Google ---
  'https://www.google.com/s2/favicons?sz=64&domain=google.com',
  'https://www.google.com/s2/favicons?sz=64&domain=gmail.com',
  'https://www.google.com/s2/favicons?sz=64&domain=drive.google.com',
  'https://www.google.com/s2/favicons?sz=64&domain=calendar.google.com',
  'https://www.google.com/s2/favicons?sz=64&domain=meet.google.com',
  // --- Microsoft ---
  'https://www.google.com/s2/favicons?sz=64&domain=office.com',
  'https://www.google.com/s2/favicons?sz=64&domain=outlook.com',
  'https://www.google.com/s2/favicons?sz=64&domain=teams.microsoft.com',
  'https://www.google.com/s2/favicons?sz=64&domain=sharepoint.com',
  'https://www.google.com/s2/favicons?sz=64&domain=azure.microsoft.com',
  // --- Dev & DevOps ---
  'https://www.google.com/s2/favicons?sz=64&domain=github.com',
  'https://www.google.com/s2/favicons?sz=64&domain=gitlab.com',
  'https://www.google.com/s2/favicons?sz=64&domain=bitbucket.org',
  'https://www.google.com/s2/favicons?sz=64&domain=grafana.com',
  'https://www.google.com/s2/favicons?sz=64&domain=portainer.io',
  'https://www.google.com/s2/favicons?sz=64&domain=jenkins.io',
  'https://www.google.com/s2/favicons?sz=64&domain=docker.com',
  // --- Project management ---
  'https://www.google.com/s2/favicons?sz=64&domain=jira.atlassian.com',
  'https://www.google.com/s2/favicons?sz=64&domain=confluence.atlassian.com',
  'https://www.google.com/s2/favicons?sz=64&domain=trello.com',
  'https://www.google.com/s2/favicons?sz=64&domain=notion.so',
  'https://www.google.com/s2/favicons?sz=64&domain=linear.app',
  // --- Communication ---
  'https://www.google.com/s2/favicons?sz=64&domain=slack.com',
  'https://www.google.com/s2/favicons?sz=64&domain=whatsapp.com',
  'https://www.google.com/s2/favicons?sz=64&domain=telegram.org',
  'https://www.google.com/s2/favicons?sz=64&domain=zoom.us',
  // --- Other common ---
  'https://www.google.com/s2/favicons?sz=64&domain=1password.com',
  'https://www.google.com/s2/favicons?sz=64&domain=bitwarden.com',
  'https://www.google.com/s2/favicons?sz=64&domain=cloudflare.com',
  'https://www.google.com/s2/favicons?sz=64&domain=aws.amazon.com',
];

function _buildIconPicker() {
  const panel = document.getElementById('icon-picker-panel');
  panel.innerHTML = '';
  _ICON_LIST.forEach(ic => {
    const btn = document.createElement('div');
    btn.className = 'icon-opt';
    btn.title = ic;
    if (ic.startsWith('http') || ic.startsWith('/')) {
      btn.innerHTML = `<img src="${escHtml(ic)}" alt="" loading="lazy" />`;
    } else {
      btn.textContent = ic;
    }
    btn.addEventListener('click', () => {
      document.getElementById('lm-icon').value = ic;
      _updateIconPreview(ic);
      panel.querySelectorAll('.icon-opt').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      panel.classList.add('hidden');
      document.getElementById('icon-pick-toggle').textContent = '🎨 Choose…';
    });
    panel.appendChild(btn);
  });
}

function _updateIconPreview(val) {
  const prev = document.getElementById('lm-icon-preview');
  if (!val) { prev.textContent = '🔗'; return; }
  if (val.startsWith('http') || val.startsWith('/')) {
    prev.innerHTML = `<img src="${escHtml(val)}" alt="" />`;
  } else {
    prev.textContent = val;
  }
  // Highlight matching option in picker
  document.querySelectorAll('#icon-picker-panel .icon-opt').forEach(b => {
    b.classList.toggle('active', b.title === val);
  });
}

document.getElementById('icon-pick-toggle').addEventListener('click', () => {
  const panel = document.getElementById('icon-picker-panel');
  const open = panel.classList.toggle('hidden') === false;
  document.getElementById('icon-pick-toggle').textContent = open ? '✕ Close' : '🎨 Choose…';
  if (open && !panel.children.length) _buildIconPicker();
  // Highlight current value
  const cur = document.getElementById('lm-icon').value.trim();
  if (cur) _updateIconPreview(cur);
});

document.getElementById('lm-icon').addEventListener('input', e => {
  _updateIconPreview(e.target.value.trim());
});

document.getElementById('link-modal-save').addEventListener('click', async () => {
  const label = document.getElementById('lm-label').value.trim();
  const url   = document.getElementById('lm-url').value.trim();
  const icon  = document.getElementById('lm-icon').value.trim();
  const desc  = document.getElementById('lm-desc').value.trim();
  if (!label || !url) { toast('Label and URL are required', 'err'); return; }
  const links = [...(_appsData.links || [])];
  const entry = { label, url, icon: icon || '🔗', description: desc };
  if (_editingLinkIdx >= 0) links[_editingLinkIdx] = entry;
  else links.push(entry);
  closeLinkModal();
  await saveLinks(links);
});

// ---- Support module ----
let _supportMeta = { categories: [], priorities: [], statuses: [], users: [] };
let _currentTicketId = null;
let _supportView = 'list';

async function loadSupport() {
  try {
    _supportMeta = await api('GET', '/api/support/meta');
    _populateSupportFilters();
    await refreshTicketList();
    _loadSupportStats();
  } catch (e) {
    toast(`Support load failed: ${e.message}`, 'err');
  }
}

async function _loadSupportStats() {
  try {
    const stats = await api('GET', '/api/support/stats');
    _renderSupportStats(stats);
  } catch (e) { /* stats optional */ }
}

function _renderSupportStats(s) {
  const bar = document.getElementById('support-stats-bar');
  const STATUS_COL = { open: 'var(--accent)', in_progress: 'var(--warn)', resolved: 'var(--success)', closed: 'var(--text-dim)' };
  const PRIO_COL   = { urgent: '#c0392b', high: 'var(--danger)', medium: 'var(--warn)', low: 'var(--text-dim)' };
  let html = '<div class="support-stats-cards">';
  ['open','in_progress','resolved','closed'].forEach(st => {
    const n = s.by_status[st] || 0;
    const col = STATUS_COL[st];
    html += `<div class="support-stat-card" style="border-color:${col}">
      <div class="support-stat-num" style="color:${col}">${n}</div>
      <div class="support-stat-label">${_capFirst(st)}</div>
    </div>`;
  });
  html += '</div>';
  // Active priority pills
  const active = ['urgent','high','medium','low'].filter(p => s.by_priority[p]);
  if (active.length) {
    html += '<div class="support-stats-prio">';
    active.forEach(p => {
      const col = PRIO_COL[p];
      html += `<span class="ticket-badge" style="border-color:${col};color:${col}">${_capFirst(p)}: ${s.by_priority[p]}</span> `;
    });
    html += '</div>';
  }
  bar.innerHTML = html;
}

function _populateSupportFilters() {
  // Category filter dropdown
  const cf = document.getElementById('support-filter-category');
  cf.innerHTML = '<option value="">All categories</option>';
  _supportMeta.categories.forEach(c => {
    const o = document.createElement('option');
    o.value = c; o.textContent = _capFirst(c);
    cf.appendChild(o);
  });
  // Category select in form
  const tf = document.getElementById('tf-category');
  tf.innerHTML = '';
  _supportMeta.categories.forEach(c => {
    const o = document.createElement('option');
    o.value = c; o.textContent = _capFirst(c);
    tf.appendChild(o);
  });
}

function _capFirst(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' ') : s; }

const _PRIORITY_COLOR = { low: 'var(--text-dim)', medium: 'var(--warn)', high: 'var(--danger)', urgent: '#c0392b' };
const _STATUS_COLOR   = { open: 'var(--accent)', in_progress: 'var(--warn)', resolved: 'var(--success)', closed: 'var(--text-dim)' };

function _badge(val, colorMap) {
  const color = colorMap[val] || 'var(--text-dim)';
  return `<span class="ticket-badge" style="border-color:${color};color:${color}">${_capFirst(val)}</span>`;
}

async function refreshTicketList() {
  if (_supportView === 'board') { _renderKanban(); return; }
  const status   = document.getElementById('support-filter-status').value;
  const priority = document.getElementById('support-filter-priority').value;
  const category = document.getElementById('support-filter-category').value;
  const qs = new URLSearchParams();
  if (status)   qs.set('status',   status);
  if (priority) qs.set('priority', priority);
  if (category) qs.set('category', category);
  try {
    const tickets = await api('GET', `/api/support/tickets?${qs}`);
    const list  = document.getElementById('tickets-list');
    const empty = document.getElementById('tickets-empty');
    list.innerHTML = '';
    empty.classList.toggle('hidden', tickets.length > 0);
    tickets.forEach(tk => {
      const row = document.createElement('div');
      row.className = 'ticket-row';
      row.innerHTML = `
        <div class="ticket-row-id">#${tk.id}</div>
        <div class="ticket-row-main">
          <div class="ticket-row-title">${escHtml(tk.title)}</div>
          <div class="ticket-row-meta">
            ${_badge(tk.priority, _PRIORITY_COLOR)}
            ${_badge(tk.status,   _STATUS_COLOR)}
            <span class="text-dim" style="font-size:0.75rem">${escHtml(tk.category)}</span>
            ${state.isAdmin ? `<span class="text-dim" style="font-size:0.75rem">by ${escHtml(tk.created_by)}</span>` : ''}
            ${tk.assigned_to ? `<span class="text-dim" style="font-size:0.75rem">→ ${escHtml(tk.assigned_to)}</span>` : ''}
          </div>
        </div>
        <div class="ticket-row-date text-dim">${escHtml((tk.updated_at||'').slice(0,10))}</div>`;
      row.addEventListener('click', () => openTicketDetail(tk.id));
      list.appendChild(row);
    });
  } catch (e) {
    toast(`Failed to load tickets: ${e.message}`, 'err');
  }
}

// Filters
['support-filter-status','support-filter-priority','support-filter-category'].forEach(id => {
  document.getElementById(id).addEventListener('change', refreshTicketList);
});

// View toggle
document.getElementById('view-list-btn').addEventListener('click', () => {
  _supportView = 'list';
  document.getElementById('support-list-view').classList.remove('hidden');
  document.getElementById('support-board-view').classList.add('hidden');
  document.getElementById('view-list-btn').classList.add('active');
  document.getElementById('view-board-btn').classList.remove('active');
  refreshTicketList();
});
document.getElementById('view-board-btn').addEventListener('click', () => {
  _supportView = 'board';
  document.getElementById('support-list-view').classList.add('hidden');
  document.getElementById('support-board-view').classList.remove('hidden');
  document.getElementById('view-list-btn').classList.remove('active');
  document.getElementById('view-board-btn').classList.add('active');
  _renderKanban();
});

async function _renderKanban() {
  try {
    // Fetch all tickets (no status filter)
    const tickets = await api('GET', '/api/support/tickets');
    const cols = ['open','in_progress','resolved','closed'];
    cols.forEach(st => {
      const body  = document.getElementById(`kb-${st}`);
      const count = document.getElementById(`kc-${st}`);
      const group = tickets.filter(t => t.status === st);
      count.textContent = `(${group.length})`;
      body.innerHTML = '';
      group.forEach(tk => {
        const card = document.createElement('div');
        card.className = 'kanban-card';
        card.draggable = true;
        card.dataset.id = tk.id;
        card.innerHTML = `
          <div class="kanban-card-id text-dim">#${tk.id}</div>
          <div class="kanban-card-title">${escHtml(tk.title)}</div>
          <div class="kanban-card-meta">
            ${_badge(tk.priority, _PRIORITY_COLOR)}
            ${tk.assigned_to ? `<span class="text-dim" style="font-size:0.7rem">→${escHtml(tk.assigned_to)}</span>` : ''}
          </div>`;
        card.addEventListener('click', () => openTicketDetail(tk.id));
        card.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', tk.id);
          card.classList.add('dragging');
        });
        card.addEventListener('dragend', () => card.classList.remove('dragging'));
        body.appendChild(card);
      });
      // Drop zone
      body.addEventListener('dragover', e => { e.preventDefault(); body.classList.add('drag-over'); });
      body.addEventListener('dragleave', () => body.classList.remove('drag-over'));
      body.addEventListener('drop', async e => {
        e.preventDefault();
        body.classList.remove('drag-over');
        const tid = parseInt(e.dataTransfer.getData('text/plain'));
        if (!tid) return;
        await api('PUT', `/api/support/tickets/${tid}`, { status: st });
        await _renderKanban();
        _loadSupportStats();
      });
    });
  } catch (err) {
    toast(`Kanban load failed: ${err.message}`, 'err');
  }
}

// New ticket
document.getElementById('new-ticket-btn').addEventListener('click', () => {
  document.getElementById('ticket-form-title').textContent = 'New Ticket';
  document.getElementById('tf-title').value = '';
  document.getElementById('tf-description').value = '';
  document.getElementById('tf-files').value = '';
  document.getElementById('ticket-form-overlay').classList.remove('hidden');
});
document.getElementById('ticket-form-close').addEventListener('click',  () => document.getElementById('ticket-form-overlay').classList.add('hidden'));
document.getElementById('ticket-form-cancel').addEventListener('click', () => document.getElementById('ticket-form-overlay').classList.add('hidden'));

document.getElementById('ticket-form-save').addEventListener('click', async () => {
  const title    = document.getElementById('tf-title').value.trim();
  const desc     = document.getElementById('tf-description').value.trim();
  const category = document.getElementById('tf-category').value;
  const priority = document.getElementById('tf-priority').value;
  const files    = document.getElementById('tf-files').files;
  if (!title || !desc) { toast('Title and description are required', 'err'); return; }
  try {
    const res = await api('POST', '/api/support/tickets', { title, description: desc, category, priority });
    // Upload attachments if any
    if (files.length) {
      const fd = new FormData();
      for (const f of files) fd.append('files', f);
      const r = await fetch(`/api/support/tickets/${res.id}/attachments`, { method: 'POST', body: fd });
      if (!r.ok) toast('Ticket created but attachment upload failed', 'err');
    }
    document.getElementById('ticket-form-overlay').classList.add('hidden');
    toast(`Ticket #${res.id} created`, 'ok');
    await refreshTicketList();
  } catch (e) {
    toast(`Failed: ${e.message}`, 'err');
  }
});

// Ticket detail
async function openTicketDetail(tid) {
  _currentTicketId = tid;
  try {
    const data = await api('GET', `/api/support/tickets/${tid}`);
    _renderTicketDetail(data);
    document.getElementById('ticket-detail-overlay').classList.remove('hidden');
  } catch (e) {
    toast(`Failed to load ticket: ${e.message}`, 'err');
  }
}

function _renderTicketDetail({ ticket: tk, comments, attachments }) {
  document.getElementById('td-title-header').textContent = `#${tk.id} — ${tk.title}`;

  // Meta bar
  const meta = document.getElementById('td-meta-bar');
  if (state.isAdmin) {
    const userOpts = (_supportMeta.users || []).map(u =>
      `<option value="${escHtml(u)}" ${tk.assigned_to===u?'selected':''}>${escHtml(u)}</option>`).join('');
    const statusOpts = (_supportMeta.statuses || []).map(s =>
      `<option value="${s}" ${tk.status===s?'selected':''}>${_capFirst(s)}</option>`).join('');
    meta.innerHTML = `
      <div class="td-meta-field">
        <label>Status</label>
        <select id="td-status">${statusOpts}</select>
      </div>
      <div class="td-meta-field">
        <label>Priority</label>
        <select id="td-priority">
          ${['low','medium','high','urgent'].map(p=>`<option value="${p}" ${tk.priority===p?'selected':''}>${_capFirst(p)}</option>`).join('')}
        </select>
      </div>
      <div class="td-meta-field">
        <label>Category</label>
        <select id="td-category">
          ${(_supportMeta.categories||[]).map(c=>`<option value="${c}" ${tk.category===c?'selected':''}>${_capFirst(c)}</option>`).join('')}
        </select>
      </div>
      <div class="td-meta-field">
        <label>Assigned to</label>
        <select id="td-assigned"><option value="">Unassigned</option>${userOpts}</select>
      </div>
      <button class="btn btn-sm btn-primary" id="td-meta-save">💾 Save</button>`;
    document.getElementById('td-meta-save').addEventListener('click', async () => {
      await api('PUT', `/api/support/tickets/${tk.id}`, {
        status:      document.getElementById('td-status').value,
        priority:    document.getElementById('td-priority').value,
        category:    document.getElementById('td-category').value,
        assigned_to: document.getElementById('td-assigned').value || null,
      });
      toast('Ticket updated', 'ok');
      await refreshTicketList();
    });
  } else {
    meta.innerHTML = `
      ${_badge(tk.priority, _PRIORITY_COLOR)} ${_badge(tk.status, _STATUS_COLOR)}
      <span class="text-dim" style="font-size:0.8rem">${escHtml(tk.category)}</span>
      ${tk.assigned_to ? `<span class="text-dim">Assigned to: ${escHtml(tk.assigned_to)}</span>` : ''}`;
  }

  // Description
  document.getElementById('td-description').innerHTML =
    `<div class="ticket-desc-body">${escHtml(tk.description).replace(/\n/g,'<br>')}</div>`;

  // Ticket-level attachments (comment_id IS NULL)
  const tkAtts = attachments.filter(a => !a.comment_id);
  const attDiv = document.getElementById('td-attachments');
  attDiv.innerHTML = tkAtts.length
    ? `<div class="ticket-att-list">${tkAtts.map(a => `<a class="ticket-att-link" href="/api/support/attachments/${a.id}" target="_blank">📎 ${escHtml(a.filename)}</a>`).join('')}</div>`
    : '';

  // Comments
  const cDiv = document.getElementById('td-comments');
  cDiv.innerHTML = '';
  comments.forEach(c => {
    const cAtts = attachments.filter(a => a.comment_id === c.id);
    const cEl = document.createElement('div');
    cEl.className = `ticket-comment ${c.author === state.user ? 'mine' : ''}`;
    cEl.innerHTML = `
      <div class="ticket-comment-header">
        <strong>${escHtml(c.author)}</strong>
        <span class="text-dim">${escHtml(c.created_at.slice(0,16).replace('T',' '))}</span>
      </div>
      <div class="ticket-comment-body">${escHtml(c.body).replace(/\n/g,'<br>')}</div>
      ${cAtts.length ? `<div class="ticket-att-list">${cAtts.map(a=>`<a class="ticket-att-link" href="/api/support/attachments/${a.id}" target="_blank">📎 ${escHtml(a.filename)}</a>`).join('')}</div>` : ''}`;
    cDiv.appendChild(cEl);
  });
  cDiv.scrollTop = cDiv.scrollHeight;
}

document.getElementById('td-close-btn').addEventListener('click', () => {
  document.getElementById('ticket-detail-overlay').classList.add('hidden');
  _currentTicketId = null;
});

document.getElementById('td-reply-files').addEventListener('change', function() {
  const names = Array.from(this.files).map(f => f.name).join(', ');
  document.getElementById('td-reply-file-names').textContent = names || '';
});

document.getElementById('td-reply-send').addEventListener('click', async () => {
  if (!_currentTicketId) return;
  const text  = document.getElementById('td-reply-text').value.trim();
  const files = document.getElementById('td-reply-files').files;
  if (!text && !files.length) { toast('Add a comment or attach a file', 'err'); return; }
  const btn = document.getElementById('td-reply-send');
  btn.disabled = true;
  try {
    let commentId = null;
    if (text) {
      const res = await api('POST', `/api/support/tickets/${_currentTicketId}/comments`, { body: text });
      commentId = res.id;
    }
    if (files.length) {
      const fd = new FormData();
      for (const f of files) fd.append('files', f);
      const url = `/api/support/tickets/${_currentTicketId}/attachments` + (commentId ? `?comment_id=${commentId}` : '');
      const r = await fetch(url, { method: 'POST', body: fd });
      if (!r.ok) toast('Comment sent but attachment failed', 'err');
    }
    document.getElementById('td-reply-text').value = '';
    document.getElementById('td-reply-files').value = '';
    document.getElementById('td-reply-file-names').textContent = '';
    const data = await api('GET', `/api/support/tickets/${_currentTicketId}`);
    _renderTicketDetail(data);
    await refreshTicketList();
  } catch (e) {
    toast(`Failed: ${e.message}`, 'err');
  } finally {
    btn.disabled = false;
  }
});

// AI assistant toggle
document.getElementById('td-ai-toggle').addEventListener('click', () => {
  const body = document.getElementById('td-ai-body');
  const chev = document.querySelector('.ai-assist-chevron');
  body.classList.toggle('hidden');
  chev.textContent = body.classList.contains('hidden') ? '▼' : '▲';
});

// Quick prompt buttons
document.querySelectorAll('.ai-assist-quick button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.getElementById('td-ai-input').value = btn.dataset.prompt;
    document.getElementById('td-ai-ask').click();
  });
});

document.getElementById('td-ai-ask').addEventListener('click', async () => {
  if (!_currentTicketId) return;
  const question = document.getElementById('td-ai-input').value.trim();
  if (!question) return;
  const respDiv = document.getElementById('td-ai-response');
  const useBtn  = document.getElementById('td-ai-use');
  respDiv.classList.remove('hidden');
  respDiv.textContent = '…';
  useBtn.classList.add('hidden');

  // Build ticket context for the AI
  let ticketCtx = '';
  try {
    const d = await api('GET', `/api/support/tickets/${_currentTicketId}`);
    const tk = d.ticket;
    ticketCtx = `Ticket #${tk.id}: ${tk.title}\nCategory: ${tk.category} | Priority: ${tk.priority} | Status: ${tk.status}\n\nDescription:\n${tk.description}`;
    if (d.comments.length) {
      ticketCtx += '\n\nComments:\n' + d.comments.map(c => `[${c.author}]: ${c.body}`).join('\n');
    }
  } catch(_) {}

  try {
    const resp = await fetch('/api/support/ai_assist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticket_context: ticketCtx, question }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    respDiv.textContent = data.answer;
    useBtn.classList.remove('hidden');
    useBtn.onclick = () => {
      document.getElementById('td-reply-text').value = data.answer;
      useBtn.classList.add('hidden');
    };
  } catch (e) {
    respDiv.textContent = `Error: ${e.message}`;
  }
});

// ---- LDAP test tool ----
document.getElementById('ldap-test-btn').addEventListener('click', async () => {
  const btn    = document.getElementById('ldap-test-btn');
  const result = document.getElementById('ldap-test-result');
  const user   = document.getElementById('ldap-test-user').value.trim();
  const pass   = document.getElementById('ldap-test-pass').value;
  result.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Testing…';
  try {
    const data = await api('POST', '/api/auth/test-ldap', { username: user, password: pass });
    const lines = [
      `Status  : ${data.ok ? '✔ Authenticated' : '✖ Failed'}`,
      data.error ? `Error   : ${data.error}` : null,
      '',
      `Groups (${(data.groups || []).length}):`,
      ...(data.groups || []).map(g => `  • ${g}`),
      '',
      `Permissions: ${JSON.stringify(data.permissions || {})}`,
      `Portal admin: ${data.is_portal_admin}`,
      `Domain admin: ${data.is_domain_admin}`,
      '',
      '--- LDAP config ---',
      `Domain  : ${data.config?.domain}`,
      `Hosts   : ${(data.config?.hosts || []).join(', ')}`,
      `Port    : ${data.config?.port}`,
      `SSL     : ${data.config?.use_ssl}   StartTLS: ${data.config?.starttls}`,
      `Base DN : ${data.config?.base_dn}`,
    ].filter(l => l !== null).join('\n');
    result.textContent = lines;
    result.style.color = data.ok ? 'var(--green, #4caf50)' : 'var(--red, #ef5350)';
  } catch (e) {
    result.textContent = `Request failed: ${e.message}`;
    result.style.color = 'var(--red, #ef5350)';
  } finally {
    result.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Test';
  }
});

// ---- Telegram (placeholder — not yet in web UI) ----
const _telToggle = document.getElementById('telegram-toggle');
if (_telToggle) {
  _telToggle.addEventListener('click', () => {
    const body    = document.getElementById('telegram-body');
    const chevron = document.getElementById('tel-chevron');
    state.telegramOpen = !state.telegramOpen;
    if (body)    body.classList.toggle('hidden', !state.telegramOpen);
    if (chevron) chevron.classList.toggle('up', state.telegramOpen);
  });
}

// ---- Audit ----
document.getElementById('audit-close-btn').addEventListener('click', () => {
  document.getElementById('audit-overlay').classList.add('hidden');
});
document.getElementById('audit-apply-btn').addEventListener('click', loadAudit);

async function openAudit() {
  document.getElementById('audit-overlay').classList.remove('hidden');
  await loadAudit();
}

async function loadAudit() {
  const ef = encodeURIComponent(document.getElementById('audit-event-filter').value);
  const uf = encodeURIComponent(document.getElementById('audit-user-filter').value);
  const tf = encodeURIComponent(document.getElementById('audit-text-filter').value);
  try {
    const res   = await api('GET', `/api/audit?event_filter=${ef}&user_filter=${uf}&text_filter=${tf}`);
    const tbody = document.getElementById('audit-body');
    tbody.innerHTML = '';
    (res.events || []).forEach(ev => {
      const d  = ev.details || {};
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escHtml(ev.ts  || '')}</td>
        <td>${escHtml(String(ev.user  || ''))}</td>
        <td>${escHtml(ev.event || '')}</td>
        <td>${escHtml(d.server || d.target || '')}</td>
        <td>${escHtml(d.ip || '')}</td>
        <td>${d.success == null ? '' : (d.success ? '✔' : '✖')}</td>`;
      tr.addEventListener('click', () => {
        document.getElementById('audit-detail').textContent = JSON.stringify(ev, null, 2);
      });
      tbody.appendChild(tr);
    });
  } catch (e) {
    toast(`Audit load failed: ${e.message}`, 'err');
  }
}

// ---- Boot ----
async function boot() {
  // Show offline banner immediately if page was opened without network
  if (!navigator.onLine) _showOfflineBanner(true);

  let cfg;
  try {
    const r = await fetch('/api/config');
    cfg = r.ok ? await r.json() : {};
  } catch {
    cfg = {};
  }

  state.authEnabled     = cfg.auth_enabled     ?? true;
  state.refreshInterval = cfg.refresh_interval || 30;
  state.auth_users      = cfg.auth_users       || [];

  await loadTranslations(cfg.default_language || 'en');
  applyPortalName(cfg.portal_name);
  applyI18n();
  document.getElementById('lang-select').value = state.lang;

  // Pre-populate server cards in "checking" state
  if (cfg.servers && cfg.servers.length) {
    cfg.servers.forEach(s => { state.servers[s.ip] = { ...s, _checking: true }; });
    renderServers();
  }

  // Already authenticated (valid session cookie)?
  if (cfg.authenticated) {
    state.user        = cfg.user;
    state.isAdmin     = cfg.is_admin;
    state.permissions = cfg.permissions || {};
    onAuthenticated();
    scheduleAutoRefresh();
    return;
  }

  // Auth disabled — auto-login silently
  if (!state.authEnabled) {
    try {
      const res = await api('POST', '/api/auth/login', { username: '', password: '' });
      state.user        = res.user;
      state.isAdmin     = res.is_admin;
      state.permissions = res.permissions || {};
      onAuthenticated();
      scheduleAutoRefresh();
    } catch {
      showLogin();
    }
    return;
  }

  showLogin();
}

boot();

// ---- VPN module ----

let _vpnIsAdmin = false;
let _vpnUsers   = [];

async function loadVpn() {
  _vpnIsAdmin = state.permissions?.vpn === 'admin' || state.isAdmin;
  _vpnUsers   = state.auth_users || [];

  // Show/hide admin panel
  const adminPanel = document.getElementById('vpn-admin-panel');
  if (_vpnIsAdmin) {
    adminPanel.classList.remove('hidden');
    _vpnPopulateUserSelect();
    _vpnBindUpload();
  } else {
    adminPanel.classList.add('hidden');
  }

  // Hide "User" column for non-admins
  const userCol = document.getElementById('vpn-col-user');
  if (userCol) userCol.style.display = _vpnIsAdmin ? '' : 'none';

  // OS tab switching
  document.querySelectorAll('.vpn-os-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.vpn-os-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.vpn-os-panel').forEach(p => p.classList.add('hidden'));
      btn.classList.add('active');
      const panel = document.getElementById(`vpn-os-${btn.dataset.os}`);
      if (panel) panel.classList.remove('hidden');
    });
  });

  await _vpnRefresh();
}

function _vpnPopulateUserSelect() {
  const sel = document.getElementById('vpn-assign-to');
  sel.innerHTML = '';
  _vpnUsers.forEach(u => {
    const o = document.createElement('option');
    o.value = u; o.textContent = u;
    sel.appendChild(o);
  });
}

function _vpnBindUpload() {
  const btn = document.getElementById('vpn-upload-btn');
  if (btn._vpnBound) return;
  btn._vpnBound = true;
  btn.addEventListener('click', async () => {
    const name       = document.getElementById('vpn-name').value.trim();
    const assignedTo = document.getElementById('vpn-assign-to').value;
    const fileInput  = document.getElementById('vpn-file');
    const statusEl   = document.getElementById('vpn-upload-status');

    if (!name) { toast('Enter a config name', 'err'); return; }
    if (!fileInput.files.length) { toast('Select a .conf file', 'err'); return; }
    const file = fileInput.files[0];
    if (!file.name.endsWith('.conf')) { toast('Only .conf files allowed', 'err'); return; }

    const fd = new FormData();
    fd.append('name', name);
    fd.append('assigned_to', assignedTo);
    fd.append('file', file);

    btn.disabled = true;
    statusEl.textContent = 'Uploading…';
    try {
      await fetch('/api/vpn/configs', { method: 'POST', credentials: 'include', body: fd })
        .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
      document.getElementById('vpn-name').value = '';
      fileInput.value = '';
      statusEl.textContent = '✓ Uploaded';
      setTimeout(() => { statusEl.textContent = ''; }, 3000);
      await _vpnRefresh();
    } catch (e) {
      toast(`Upload failed: ${e.message}`, 'err');
      statusEl.textContent = '';
    } finally {
      btn.disabled = false;
    }
  });
}

async function _vpnRefresh() {
  try {
    const { configs } = await api('GET', '/api/vpn/configs');
    _vpnRender(configs);
  } catch (e) {
    toast(`VPN load failed: ${e.message}`, 'err');
  }
}

function _vpnRender(configs) {
  const table  = document.getElementById('vpn-table');
  const tbody  = document.getElementById('vpn-tbody');
  const empty  = document.getElementById('vpn-empty');

  if (!configs.length) {
    table.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }
  table.classList.remove('hidden');
  empty.classList.add('hidden');

  tbody.innerHTML = '';
  configs.forEach(cfg => {
    const tr = document.createElement('tr');
    const date = cfg.created_at ? cfg.created_at.slice(0, 10) : '';
    tr.innerHTML = `
      <td>${escHtml(cfg.name)}</td>
      <td><code>${escHtml(cfg.filename)}</code></td>
      <td ${_vpnIsAdmin ? '' : 'style="display:none"'}>${escHtml(cfg.assigned_to)}</td>
      <td>${escHtml(cfg.uploaded_by)}</td>
      <td class="text-dim">${escHtml(date)}</td>
      <td class="vpn-actions">
        <a class="btn btn-sm btn-primary" href="/api/vpn/configs/${cfg.id}/download">⬇ Download</a>
        ${_vpnIsAdmin ? `<button class="btn btn-sm btn-danger vpn-del-btn" data-id="${cfg.id}" data-name="${escHtml(cfg.name)}">🗑</button>` : ''}
      </td>
    `;
    tbody.appendChild(tr);
  });

  // Bind delete buttons
  tbody.querySelectorAll('.vpn-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(`Delete config "${btn.dataset.name}"?`)) return;
      try {
        await api('DELETE', `/api/vpn/configs/${btn.dataset.id}`);
        await _vpnRefresh();
      } catch (e) {
        toast(`Delete failed: ${e.message}`, 'err');
      }
    });
  });
}

// ---- Wiki module ----

let _wikiIsAdmin  = false;
let _wikiCatSlug  = null;
let _wikiArtSlug  = null;
let _wikiEditing  = false;  // true = new, 'slug' = editing existing
let _easyMDE      = null;

function _initEasyMDE() {
  if (_easyMDE) return;
  _easyMDE = new EasyMDE({
    element: document.getElementById('wiki-ed-body'),
    spellChecker: false,
    autosave: { enabled: false },
    minHeight: '320px',
    placeholder: 'Write content here…',
    toolbar: [
      'bold', 'italic', 'heading', '|',
      'quote', 'unordered-list', 'ordered-list', '|',
      'link', 'table', '|',
      'preview', 'side-by-side', 'fullscreen', '|',
      'guide',
    ],
    previewRender: (text) => _md(text),
  });
}

function _initMarkdownPlugins() {
  if (typeof marked === 'undefined' || _initMarkdownPlugins._done) return;
  _initMarkdownPlugins._done = true;
  marked.use({
    renderer: {
      code(text, lang) {
        // marked v12 passes (text, lang, escaped) — handle both signatures
        const rawText = typeof text === 'object' ? text.text : text;
        const rawLang = typeof text === 'object' ? text.lang : (lang || '');
        if (rawLang === 'mermaid') {
          return `<div class="cobaltax-mermaid" style="margin:1.2rem 0;">${escHtml(rawText)}</div>`;
        }
        if (rawLang === 'drawio') {
          const json = JSON.stringify({ highlight: '#0000ff', nav: true, resize: true, xml: rawText });
          const safe = json.replace(/'/g, '&#39;');
          return `<div class="mxgraph cobaltax-drawio" style="max-width:100%;overflow:hidden;border:1px solid var(--border,#ddd);border-radius:6px;margin:1.2rem 0;background:#fff;" data-mxgraph='${safe}'></div>`;
        }
        return false;
      }
    }
  });
}

function _md(text) {
  _initMarkdownPlugins();
  return typeof marked !== 'undefined' ? marked.parse(text || '') : `<pre>${escHtml(text || '')}</pre>`;
}

function _renderDiagrams(container) {
  if (!container) return;
  // Mermaid diagrams
  const mermaidEls = container.querySelectorAll('.cobaltax-mermaid');
  if (mermaidEls.length > 0 && window.mermaid) {
    mermaidEls.forEach((el, i) => {
      const id = 'mermaid-' + Date.now() + '-' + i;
      const src = el.textContent || '';
      el.innerHTML = '';
      mermaid.render(id, src).then(({ svg }) => { el.innerHTML = svg; }).catch(e => {
        el.innerHTML = `<pre style="color:red;font-size:11px;">Mermaid error: ${escHtml(String(e))}</pre>`;
      });
    });
  }
  // draw.io diagrams
  if (window.GraphViewer && container.querySelectorAll('.mxgraph').length > 0) {
    try { GraphViewer.processElements(container); } catch(e) { console.warn('draw.io:', e); }
  }
}

async function loadWiki() {
  _wikiIsAdmin = state.permissions?.wiki === 'admin' || state.isAdmin;

  // Show admin buttons
  ['wiki-new-cat-btn', 'wiki-new-art-btn', 'wiki-edit-btn', 'wiki-del-art-btn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', !_wikiIsAdmin);
  });

  _wikiBindSearch();
  _wikiBindNewCat();
  _wikiBindEditor();

  await _wikiLoadCategories();
}

async function _wikiLoadCategories() {
  const { categories } = await api('GET', '/api/wiki/categories');
  const panel = document.getElementById('wiki-cats');
  const empty = document.getElementById('wiki-cats-empty');
  panel.querySelectorAll('.wiki-cat-item').forEach(el => el.remove());

  if (!categories.length) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  categories.forEach(cat => {
    const el = document.createElement('div');
    el.className = 'wiki-cat-item' + (_wikiCatSlug === cat.slug ? ' active' : '');
    el.dataset.slug = cat.slug;
    el.innerHTML = `
      <span class="wiki-cat-name">${escHtml(cat.name)}</span>
      ${_wikiIsAdmin ? `<button class="wiki-cat-del btn btn-xs btn-danger" title="Delete category">✕</button>` : ''}
    `;
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('wiki-cat-del')) return;
      _wikiSelectCat(cat.slug);
    });
    if (_wikiIsAdmin) {
      el.querySelector('.wiki-cat-del').addEventListener('click', async () => {
        const arts = (await api('GET', `/api/wiki/categories/${cat.slug}/articles`)).articles;
        const msg = arts.length
          ? `Delete category "${cat.name}" and its ${arts.length} article(s)?`
          : `Delete category "${cat.name}"?`;
        if (!confirm(msg)) return;
        await api('DELETE', `/api/wiki/categories/${cat.slug}`);
        if (_wikiCatSlug === cat.slug) { _wikiCatSlug = null; _wikiClearContent(); }
        await _wikiLoadCategories();
      });
    }
    panel.appendChild(el);
  });

  // Restore selected category
  if (_wikiCatSlug) await _wikiLoadArticles(_wikiCatSlug);
}

async function _wikiSelectCat(slug) {
  _wikiCatSlug = slug;
  _wikiArtSlug = null;
  document.querySelectorAll('.wiki-cat-item').forEach(el =>
    el.classList.toggle('active', el.dataset.slug === slug));
  const newArtBtn = document.getElementById('wiki-new-art-btn');
  if (newArtBtn) newArtBtn.disabled = false;
  await _wikiLoadArticles(slug);
  _wikiClearContent();
}

async function _wikiLoadArticles(catSlug) {
  const { articles } = await api('GET', `/api/wiki/categories/${catSlug}/articles`);
  const list  = document.getElementById('wiki-art-list');
  const empty = document.getElementById('wiki-arts-empty');
  list.innerHTML = '';

  if (!articles.length) {
    list.classList.add('hidden');
    empty.classList.remove('hidden');
    empty.textContent = 'No articles yet.';
    return;
  }
  list.classList.remove('hidden');
  empty.classList.add('hidden');

  articles.forEach(art => {
    const li = document.createElement('li');
    li.className = 'wiki-art-item' + (_wikiArtSlug === art.slug ? ' active' : '');
    li.dataset.slug = art.slug;
    li.innerHTML = `<span class="wiki-art-item-title">${escHtml(art.title)}</span>
                    <span class="wiki-art-item-date text-dim">${(art.updated_at || '').slice(0, 10)}</span>`;
    li.addEventListener('click', () => _wikiOpenArticle(catSlug, art.slug));
    list.appendChild(li);
  });
}

async function _wikiOpenArticle(catSlug, artSlug) {
  _wikiArtSlug = artSlug;
  _wikiEditing = false;

  document.querySelectorAll('.wiki-art-item').forEach(el =>
    el.classList.toggle('active', el.dataset.slug === artSlug));

  const { article } = await api('GET', `/api/wiki/articles/${catSlug}/${artSlug}`);
  _wikiShowView(article);
}

function _wikiShowView(art) {
  document.getElementById('wiki-editor').classList.add('hidden');
  document.getElementById('wiki-content-hint').classList.add('hidden');
  const view = document.getElementById('wiki-article-view');
  view.classList.remove('hidden');

  document.getElementById('wiki-art-title').textContent = art.title;
  document.getElementById('wiki-art-date').textContent  = 'Updated: ' + (art.updated_at || '').slice(0, 10);
  document.getElementById('wiki-art-author').textContent = art.author ? `by ${art.author}` : '';

  const tagsEl = document.getElementById('wiki-art-tags');
  tagsEl.innerHTML = (art.tags || []).map(t => `<span class="wiki-tag">${escHtml(t)}</span>`).join('');

  const _artBody = document.getElementById('wiki-art-body');
  _artBody.innerHTML = _md(art.content);
  _renderDiagrams(_artBody);

  // Edit / Delete bindings
  const editBtn = document.getElementById('wiki-edit-btn');
  const delBtn  = document.getElementById('wiki-del-art-btn');
  if (editBtn) {
    editBtn.onclick = () => _wikiOpenEditor(art);
  }
  if (delBtn) {
    delBtn.onclick = async () => {
      if (!confirm(`Delete article "${art.title}"?`)) return;
      await api('DELETE', `/api/wiki/articles/${_wikiCatSlug}/${art.slug}`);
      _wikiArtSlug = null;
      _wikiClearContent();
      await _wikiLoadArticles(_wikiCatSlug);
    };
  }
}

function _wikiClearContent() {
  document.getElementById('wiki-article-view').classList.add('hidden');
  document.getElementById('wiki-editor').classList.add('hidden');
  document.getElementById('wiki-content-hint').classList.remove('hidden');
}

function _wikiOpenEditor(art = null) {
  _wikiEditing = art ? art.slug : true;
  document.getElementById('wiki-article-view').classList.add('hidden');
  document.getElementById('wiki-content-hint').classList.add('hidden');
  const editor = document.getElementById('wiki-editor');
  editor.classList.remove('hidden');
  document.getElementById('wiki-ed-title').value = art ? art.title : '';
  document.getElementById('wiki-ed-tags').value  = art ? (art.tags || []).join(', ') : '';
  _initEasyMDE();
  _easyMDE.value(art ? art.content : '');
  _easyMDE.codemirror.refresh();
  document.getElementById('wiki-ed-title').focus();
}

function _wikiBindEditor() {
  const saveBtn   = document.getElementById('wiki-ed-save-btn');
  const cancelBtn = document.getElementById('wiki-ed-cancel-btn');
  const newArtBtn = document.getElementById('wiki-new-art-btn');

  if (newArtBtn && !newArtBtn._wikiBound) {
    newArtBtn._wikiBound = true;
    newArtBtn.addEventListener('click', () => _wikiOpenEditor(null));
  }

  if (saveBtn && !saveBtn._wikiBound) {
    saveBtn._wikiBound = true;
    saveBtn.addEventListener('click', async () => {
      const title   = document.getElementById('wiki-ed-title').value.trim();
      const content = _easyMDE ? _easyMDE.value() : document.getElementById('wiki-ed-body').value;
      const tags    = document.getElementById('wiki-ed-tags').value
                        .split(',').map(t => t.trim()).filter(Boolean);
      if (!title) { toast('Title required', 'err'); return; }
      if (!_wikiCatSlug) { toast('Select a category first', 'err'); return; }

      saveBtn.disabled = true;
      try {
        let art;
        if (_wikiEditing === true) {
          // new article
          const r = await api('POST', `/api/wiki/articles/${_wikiCatSlug}`, { title, content, tags });
          art = r.article;
          _wikiArtSlug = art.slug;
        } else {
          // update existing
          const r = await api('PUT', `/api/wiki/articles/${_wikiCatSlug}/${_wikiEditing}`, { title, content, tags });
          art = r.article;
        }
        await _wikiLoadArticles(_wikiCatSlug);
        _wikiShowView(art);
        _wikiEditing = false;
      } catch (e) {
        toast(`Save failed: ${e.message}`, 'err');
      } finally {
        saveBtn.disabled = false;
      }
    });
  }

  if (cancelBtn && !cancelBtn._wikiBound) {
    cancelBtn._wikiBound = true;
    cancelBtn.addEventListener('click', () => {
      _wikiEditing = false;
      if (_wikiArtSlug) {
        _wikiOpenArticle(_wikiCatSlug, _wikiArtSlug);
      } else {
        _wikiClearContent();
      }
    });
  }
}

function _wikiBindNewCat() {
  const btn = document.getElementById('wiki-new-cat-btn');
  if (!btn || btn._wikiBound) return;
  btn._wikiBound = true;
  btn.addEventListener('click', async () => {
    const name = prompt('Category name:');
    if (!name || !name.trim()) return;
    const desc = prompt('Description (optional):') || '';
    await api('POST', '/api/wiki/categories', { name: name.trim(), description: desc });
    await _wikiLoadCategories();
  });
}

let _wikiSearchTimer = null;
function _wikiBindSearch() {
  const input = document.getElementById('wiki-search');
  const dd    = document.getElementById('wiki-search-results');
  if (!input || input._wikiBound) return;
  input._wikiBound = true;

  input.addEventListener('input', () => {
    clearTimeout(_wikiSearchTimer);
    const q = input.value.trim();
    if (q.length < 2) { dd.classList.add('hidden'); return; }
    _wikiSearchTimer = setTimeout(async () => {
      const { results } = await api('GET', `/api/wiki/search?q=${encodeURIComponent(q)}`);
      dd.innerHTML = '';
      if (!results.length) {
        dd.innerHTML = '<div class="wiki-search-no-result">No results</div>';
      } else {
        results.slice(0, 8).forEach(r => {
          const el = document.createElement('div');
          el.className = 'wiki-search-result';
          el.innerHTML = `<strong>${escHtml(r.title)}</strong>
                          <span class="text-dim">${escHtml(r.cat_name)}</span>
                          <span class="wiki-search-excerpt">${escHtml(r.excerpt)}</span>`;
          el.addEventListener('click', async () => {
            dd.classList.add('hidden');
            input.value = '';
            await _wikiSelectCat(r.cat_slug);
            await _wikiOpenArticle(r.cat_slug, r.slug);
          });
          dd.appendChild(el);
        });
      }
      dd.classList.remove('hidden');
    }, 250);
  });

  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !dd.contains(e.target)) dd.classList.add('hidden');
  });
}

// ---- Printer health chips (health section) ----
async function loadPrinterHealth() {
  const container = document.getElementById('printers-health');
  if (!container) return;
  try {
    if (!_printers.length) _printers = await api('GET', '/api/printers');
    _printers.forEach(p => { if (_printerStatus[p.ip] === undefined) _printerStatus[p.ip] = null; });
    _renderPrinterHealth();
    const fresh = await api('GET', '/api/printers/ping');
    Object.assign(_printerStatus, fresh);
    _renderPrinterHealth();
  } catch (e) {
    container.innerHTML = '';
  }
}

function _renderPrinterHealth() {
  const container = document.getElementById('printers-health');
  if (!container || !_printers.length) return;

  container.innerHTML = '';

  // Group printers by subnet
  const bySubnet = {};
  _printers.forEach(p => {
    const key = p.subnet || _detectSubnet(p.ip);
    (bySubnet[key] = bySubnet[key] || []).push(p);
  });

  const subnetKeys = _SUBNET_ORDER.filter(k => bySubnet[k])
    .concat(Object.keys(bySubnet).filter(k => !_SUBNET_ORDER.includes(k)));

  subnetKeys.forEach(subnet => {
    const list = bySubnet[subnet];
    const onlineCount = list.filter(p => _printerStatus[p.ip] === true).length;

    const section = document.createElement('div');
    section.className = 'subnet-section';

    const hdr = document.createElement('div');
    hdr.className = 'subnet-header';
    hdr.innerHTML = `<span class="subnet-label">${escHtml(_subnetLabel(subnet))}</span>`
      + `<span class="subnet-count">${onlineCount}/${list.length} online</span>`;
    section.appendChild(hdr);

    const chips = document.createElement('div');
    chips.className = 'printer-chips';

    list.forEach(p => {
      const online = _printerStatus[p.ip];
      const cls = online === null ? 'checking' : (online ? 'online' : 'offline');
      const chip = document.createElement('div');
      chip.className = `printer-chip ${cls}`;
      chip.innerHTML =
        `<span class="status-dot ${cls}"></span>`
        + `<span class="printer-chip-name">${escHtml(p.name)}</span>`
        + (p.location ? `<span class="printer-chip-loc">${escHtml(p.location)}</span>` : '')
        + `<a class="printer-chip-link" href="http://${escHtml(p.ip)}/" target="_blank" rel="noopener" title="Open web UI">🌐</a>`;
      chips.appendChild(chip);
    });

    section.appendChild(chips);
    container.appendChild(section);
  });
}

// ---- Health: Application monitoring ----
async function loadHealthApps() {
  const container = document.getElementById('apps-health');
  if (!container) return;
  try {
    const apps = await api('GET', '/api/apps/monitor');
    _renderHealthApps(apps, container);
  } catch { /* non-fatal */ }
}

function _renderHealthApps(apps, container) {
  container.innerHTML = '';
  if (!apps || !apps.length) return;

  const section = document.createElement('div');
  section.className = 'subnet-section';

  const hdr = document.createElement('div');
  hdr.className = 'subnet-header';
  const onlineCount = apps.filter(a => a.online).length;
  hdr.innerHTML = `<span class="subnet-label">${escHtml(t('health_apps'))}</span>`
    + `<span class="subnet-count">${onlineCount}/${apps.length} online</span>`;
  section.appendChild(hdr);

  const chips = document.createElement('div');
  chips.className = 'printer-chips';

  apps.forEach(a => {
    const cls = a.online ? 'online' : 'offline';
    const chip = document.createElement('div');
    chip.className = `printer-chip ${cls}`;
    chip.innerHTML =
      `<span class="status-dot ${cls}"></span>`
      + `<span class="printer-chip-name">${escHtml(a.name)}</span>`
      + `<span class="printer-chip-loc">${escHtml(a.server || '')}</span>`
      + `<a class="printer-chip-link" href="${escHtml(a.url)}" target="_blank" rel="noopener" title="Open">🌐</a>`;
    chips.appendChild(chip);
  });

  section.appendChild(chips);
  container.appendChild(section);
}

// ---- Health: Backup monitoring ----
async function loadHealthBackups() {
  const container = document.getElementById('backups-health');
  if (!container) return;
  try {
    const backups = await api('GET', '/api/backups');
    _renderHealthBackups(backups, container);
  } catch { /* non-fatal */ }
}

function _renderHealthBackups(backups, container) {
  container.innerHTML = '';
  if (!backups || !backups.length) return;

  const section = document.createElement('div');
  section.className = 'subnet-section';

  const hdr = document.createElement('div');
  hdr.className = 'subnet-header';
  hdr.innerHTML = `<span class="subnet-label">${escHtml(t('health_backups'))}</span>`;
  section.appendChild(hdr);

  const grid = document.createElement('div');
  grid.className = 'backup-cards';

  backups.forEach(b => {
    const card = document.createElement('div');
    card.className = 'backup-card';
    card.innerHTML =
      `<div class="backup-name">${escHtml(b.name)}</div>`
      + `<div class="backup-meta"><span>${escHtml(t('backup_last_backup'))}</span> ${escHtml(b.last_backup)}</div>`
      + `<div class="backup-meta"><span>${escHtml(t('backup_retention'))}</span> ${escHtml(b.retention)}</div>`
      + `<button class="btn btn-sm btn-restore" data-id="${escHtml(b.id)}" data-name="${escHtml(b.name)}">`
      + escHtml(t('backup_request_restore')) + `</button>`;
    grid.appendChild(card);
  });

  section.appendChild(grid);
  container.appendChild(section);

  // Bind restore buttons
  container.querySelectorAll('.btn-restore').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const name = btn.dataset.name;
      const confirmMsg = t('backup_restore_confirm').replace('{name}', name);
      const note = prompt(confirmMsg);
      if (note === null) return; // cancelled
      try {
        await api('POST', '/api/backups/restore', { backup_id: id, note });
        toast(t('backup_restore_sent'), 'ok', 6000);
      } catch (e) {
        toast(e.message, 'err');
      }
    });
  });
}

// ---- Energy module ----
const _ENERGY_PERIODS = ['1h', '24h', '7d', '30d'];
const _ENERGY_PERIOD_KEYS = { '1h': 'energy_1h', '24h': 'energy_24h', '7d': 'energy_7d', '30d': 'energy_30d' };

async function loadEnergy() {
  try {
    const data = await api('GET', '/api/energy');
    _renderEnergy(data);
  } catch (e) {
    document.getElementById('energy-table-wrap').innerHTML =
      `<p class="text-dim">${escHtml(e.message)}</p>`;
  }

  if (state.isAdmin) {
    const bar = document.getElementById('energy-settings-bar');
    bar.classList.remove('hidden');
    try {
      const cfg = await api('GET', '/api/energy/settings');
      document.getElementById('energy-price-input').value = cfg.price_kwh;
    } catch { /* non-fatal */ }
    document.getElementById('energy-price-save').onclick = async () => {
      const price = parseFloat(document.getElementById('energy-price-input').value);
      if (isNaN(price) || price <= 0) return;
      try {
        await api('POST', '/api/energy/settings', { price_kwh: price });
        toast(t('energy_price_saved'), 'ok');
        loadEnergy();
      } catch (e) { toast(e.message, 'err'); }
    };
  }
}

function _fmtCost(v) {
  if (v >= 10)   return v.toFixed(2);
  if (v >= 1)    return v.toFixed(2);
  if (v >= 0.01) return v.toFixed(3);
  if (v >= 0.001)return v.toFixed(4);
  return v > 0 ? '<0.001' : '0.000';
}

function _renderEnergy(data) {
  const currency = data.currency || '€';
  const totals   = data.totals   || {};
  const servers  = data.servers  || [];

  // Summary cards
  const summaryEl = document.getElementById('energy-summary');
  summaryEl.innerHTML = '';

  // Historical period cards
  _ENERGY_PERIODS.forEach(p => {
    const info = totals[p] || { kwh: 0, cost: 0, coverage: 0 };
    const cov  = info.coverage ?? 1;
    const card = document.createElement('div');
    card.className = 'energy-summary-card' + (cov < 0.8 ? ' energy-card-partial' : '');
    const costStr = cov < 0.05 ? '—'
                  : (cov < 0.8 ? `~${currency}${_fmtCost(info.cost)}` : `${currency}${_fmtCost(info.cost)}`);
    const kwhStr  = cov < 0.05 ? '—'
                  : `${info.kwh.toFixed(3)} kWh${cov < 0.8 ? ` (${Math.round(cov*100)}%)` : ''}`;
    card.innerHTML =
      `<div class="energy-period-label">${escHtml(t(_ENERGY_PERIOD_KEYS[p]))}</div>`
      + `<div class="energy-cost">${costStr}</div>`
      + `<div class="energy-kwh">${kwhStr}</div>`;
    summaryEl.appendChild(card);
  });

  // Projected month card
  const proj = totals['projected_month'];
  if (proj) {
    const card = document.createElement('div');
    card.className = 'energy-summary-card energy-projection-card';
    card.innerHTML =
      `<div class="energy-period-label">${escHtml(t('energy_projected_month'))}</div>`
      + `<div class="energy-cost">${currency}${_fmtCost(proj.cost)}</div>`
      + `<div class="energy-kwh">${proj.kwh.toFixed(1)} kWh · ${Math.round(proj.watts)} W avg</div>`;
    summaryEl.appendChild(card);
  }

  // Per-server table
  const wrap = document.getElementById('energy-table-wrap');
  if (!servers.length) {
    wrap.innerHTML = `<p class="text-dim">${escHtml(t('energy_no_data'))}</p>`;
    return;
  }

  // Sort: physical hosts first (in original order), VMs grouped under their parent
  const physical = servers.filter(s => !s.is_vm);
  const vms      = servers.filter(s => s.is_vm);
  const sorted   = [];
  physical.forEach(host => {
    sorted.push(host);
    vms.filter(vm => vm.parent === host.ip).forEach(vm => sorted.push(vm));
  });
  // Any VMs whose parent isn't in the list (edge case)
  vms.filter(vm => !physical.find(h => h.ip === vm.parent)).forEach(vm => sorted.push(vm));

  const cols = ['1h', '24h', '7d', '30d'];
  let html = `<div class="table-wrap"><table class="data-table energy-table">
    <thead><tr>
      <th>${escHtml(t('energy_server'))}</th>
      <th>${escHtml(t('energy_watts'))}</th>`;
  cols.forEach(p => {
    html += `<th>${escHtml(t(_ENERGY_PERIOD_KEYS[p]))}</th>`;
  });
  html += `</tr></thead><tbody>`;

  sorted.forEach(srv => {
    const isVm   = srv.is_vm;
    const wVal   = srv.current_watts != null ? Math.round(srv.current_watts) : null;
    const wattsStr = isVm ? '↳' : (wVal != null ? `${wVal} W` : '—');
    const rowCls = isVm ? ' class="energy-vm-row"' : '';
    const indent = isVm ? '<span class="energy-vm-indent">└</span> ' : '';
    html += `<tr${rowCls}>
      <td>${indent}<span class="os-badge">${escHtml(osBadge(srv.os_type))}</span> ${escHtml(srv.name)}${isVm ? ' <span class="energy-vm-badge">VM</span>' : ''}</td>
      <td class="energy-watts-cell">${escHtml(wattsStr)}</td>`;
    cols.forEach(p => {
      if (isVm) {
        html += `<td class="text-dim energy-vm-cell">in host</td>`;
      } else {
        const info = srv.periods?.[p] || { kwh: 0, cost: 0, coverage: 0 };
        const cov  = info.coverage ?? 1;
        if (cov < 0.05) {
          html += `<td class="text-dim">—</td>`;
        } else {
          const approx = cov < 0.8 ? '~' : '';
          const pct    = cov < 0.8 ? ` <span class="energy-coverage">${Math.round(cov*100)}%</span>` : '';
          html += `<td><strong class="energy-cost-cell">${approx}${currency}${_fmtCost(info.cost)}</strong>${pct}<br><small class="text-dim">${info.kwh.toFixed(3)} kWh</small></td>`;
        }
      }
    });
    html += `</tr>`;
  });

  // Totals row — show live total watts from projected_month data
  const totalWatts = totals.projected_month?.watts;
  const totalWattsStr = totalWatts != null ? `${Math.round(totalWatts)} W` : '—';
  html += `<tr class="energy-total-row"><td><strong>TOTAL</strong></td><td class="energy-watts-cell"><strong>${escHtml(totalWattsStr)}</strong></td>`;
  cols.forEach(p => {
    const info = totals[p] || { kwh: 0, cost: 0, coverage: 0 };
    const cov  = info.coverage ?? 1;
    if (cov < 0.05) {
      html += `<td class="text-dim">—</td>`;
    } else {
      const approx = cov < 0.8 ? '~' : '';
      const pct    = cov < 0.8 ? ` <span class="energy-coverage">${Math.round(cov*100)}%</span>` : '';
      html += `<td><strong>${approx}${currency}${_fmtCost(info.cost)}</strong>${pct}<br><small class="text-dim">${info.kwh.toFixed(3)} kWh</small></td>`;
    }
  });
  html += `</tr></tbody></table></div>`;

  wrap.innerHTML = html;
}

// ---- AI Chat module ----
let _chatMessages      = [];
let _chatStreaming      = false;
let _currentConvId     = null;
let _convListEl        = null;
let _wikiInterviewMode = false;
let _chatInitialized   = false;

async function initAiChat() {
  _convListEl = document.getElementById('conv-list');

  // Bind buttons (idempotent — safe to run on every tab visit)
  const newBtn = document.getElementById('conv-new-btn');
  if (newBtn && !newBtn._bound) {
    newBtn._bound = true;
    newBtn.onclick = () => _newConversation();
  }
  const interviewBtn = document.getElementById('wiki-interview-btn');
  if (interviewBtn && !interviewBtn._bound) {
    interviewBtn._bound = true;
    interviewBtn.onclick = () => _toggleWikiInterviewMode();
  }

  // Skip full reload on subsequent tab visits — avoids lag and unnecessary re-render
  if (_chatInitialized) return;
  _chatInitialized = true;

  // API key banner (only on first load)
  try {
    const status = await api('GET', '/api/chat/status');
    const banner = document.getElementById('ai-setup-banner');
    if (!status.has_key) {
      banner.classList.remove('hidden');
      document.getElementById('ai-setup-btn').onclick = () => {
        const key = prompt(t('ai_enter_key'));
        if (!key) return;
        api('POST', '/api/chat/key', { key })
          .then(() => { banner.classList.add('hidden'); toast(t('ai_key_saved'), 'ok'); })
          .catch(e => toast(e.message, 'err'));
      };
    } else {
      banner.classList.add('hidden');
    }
  } catch { /* non-fatal */ }

  // Load conversation list and open the most recent (or create first)
  await _loadConversations();
}

async function _toggleWikiInterviewMode() {
  _wikiInterviewMode = !_wikiInterviewMode;
  const btn  = document.getElementById('wiki-interview-btn');
  const main = document.querySelector('.ai-chat-main');
  if (_wikiInterviewMode) {
    btn.textContent = '📖 Interview ON';
    btn.classList.add('interview-active');
    main.classList.add('interview-mode');
    // Open a fresh conversation and kick off the AI
    await _newConversation();
    // Send a silent trigger so the AI introduces itself
    const triggerEl = document.createElement('span');
    triggerEl.textContent = 'start';
    triggerEl.style.display = 'none';
    _chatMessages.push({ role: 'user', content: 'start' });
    _chatStreaming = true;
    document.getElementById('chat-send-btn').disabled = true;
    const typingBubble = _chatTypingIndicator();
    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: _chatMessages, conversation_id: _currentConvId, mode: 'wiki_interview' }),
      });
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
      typingBubble.innerHTML = '';
      const textNode = document.createElement('div');
      typingBubble.appendChild(textNode);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '', fullText = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n'); buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'text') { fullText += evt.text; textNode.innerHTML = _md(fullText); typingBubble.parentElement?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }
          else if (evt.type === 'done') break;
        }
      }
      _chatMessages.push({ role: 'assistant', content: fullText });
      api('GET', '/api/chat/conversations').then(convs => _renderConvList(convs)).catch(() => {});
    } catch (e) {
      typingBubble.innerHTML = `<span style="color:var(--offline)">Error: ${escHtml(e.message)}</span>`;
    } finally {
      _chatStreaming = false;
      document.getElementById('chat-send-btn').disabled = false;
    }
  } else {
    btn.textContent = '📖 Wiki Interview';
    btn.classList.remove('interview-active');
    main.classList.remove('interview-mode');
  }
}

async function _loadConversations() {
  try {
    const convs = await api('GET', '/api/chat/conversations');
    _renderConvList(convs);
    if (convs.length > 0) {
      if (_currentConvId && convs.find(c => c.id === _currentConvId)) {
        await _openConversation(_currentConvId); // re-open current
      } else {
        await _openConversation(convs[0].id);
      }
    } else {
      await _newConversation();
    }
  } catch (e) {
    document.getElementById('chat-messages').innerHTML =
      `<p class="text-dim">${escHtml(e.message)}</p>`;
  }
}

function _buildConvItem(c) {
  const item = document.createElement('div');
  item.className = 'conv-item' + (c.id === _currentConvId ? ' active' : '');
  item.dataset.id = c.id;

  const titleSpan = document.createElement('span');
  titleSpan.className = 'conv-title';
  titleSpan.textContent = c.title;
  titleSpan.title = 'Double-click to rename';

  const countSpan = document.createElement('span');
  countSpan.className = 'conv-count';
  countSpan.textContent = c.msg_count || '';

  const delBtn = document.createElement('button');
  delBtn.className = 'conv-delete-btn';
  delBtn.title = 'Delete';
  delBtn.textContent = '✕';

  item.appendChild(titleSpan);
  item.appendChild(countSpan);
  item.appendChild(delBtn);

  // Double-click title → inline rename
  titleSpan.addEventListener('dblclick', e => {
    e.stopPropagation();
    const input = document.createElement('input');
    input.className = 'conv-rename-input';
    input.value = titleSpan.textContent;
    item.replaceChild(input, titleSpan);
    input.focus();
    input.select();

    const commit = async () => {
      const newTitle = input.value.trim();
      if (newTitle && newTitle !== c.title) {
        try {
          await api('PATCH', `/api/chat/conversations/${c.id}`, { title: newTitle });
          c.title = newTitle;
          titleSpan.textContent = newTitle;
        } catch (err) {
          toast(`Rename failed: ${err.message}`, 'err');
        }
      }
      item.replaceChild(titleSpan, input);
    };

    input.addEventListener('blur', commit);
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
      if (e.key === 'Escape') { input.value = c.title; input.blur(); }
    });
  });

  item.addEventListener('click', e => {
    if (e.target.classList.contains('conv-delete-btn')) return;
    if (e.target.classList.contains('conv-rename-input')) return;
    _openConversation(c.id);
  });

  delBtn.addEventListener('click', async e => {
    e.stopPropagation();
    if (!confirm(t('ai_delete_conv_confirm'))) return;
    await api('DELETE', `/api/chat/conversations/${c.id}`);
    if (_currentConvId === c.id) _currentConvId = null;
    await _loadConversations();
  });

  return item;
}

function _renderConvList(convs) {
  if (!_convListEl) return;
  _convListEl.innerHTML = '';
  convs.forEach(c => _convListEl.appendChild(_buildConvItem(c)));
}

function _convDefaultTitle() {
  const now = new Date();
  const d = now.toLocaleDateString('es', { day: '2-digit', month: '2-digit' });
  const h = now.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  return `Chat ${d} ${h}`;
}

async function _newConversation() {
  const title = _convDefaultTitle();
  const conv = await api('POST', '/api/chat/conversations', { title });
  _currentConvId = conv.id;
  _chatMessages  = [];
  document.getElementById('chat-messages').innerHTML = '';

  // Update sidebar: deactivate all items, prepend the new one, flash it
  _convListEl?.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
  if (_convListEl) {
    const item = _buildConvItem({ id: conv.id, title, msg_count: 0 });
    item.classList.add('active', 'conv-flash');
    _convListEl.prepend(item);
    item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setTimeout(() => item.classList.remove('conv-flash'), 700);
  }
}

async function _openConversation(id) {
  _currentConvId = id;
  _chatMessages  = [];
  const messagesEl = document.getElementById('chat-messages');
  messagesEl.innerHTML = '';

  // Highlight active in sidebar
  _convListEl?.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.id) === id);
  });

  try {
    const history = await api('GET', `/api/chat/history?conv=${id}`);
    history.forEach(msg => {
      _chatMessages.push({ role: msg.role, content: msg.content });
      const contentEl = document.createElement('div');
      if (msg.role === 'assistant') {
        contentEl.innerHTML = _md(msg.content);
      } else {
        contentEl.textContent = msg.content;
      }
      _chatAppendMsg(msg.role, contentEl);
    });
    if (history.length) messagesEl.lastElementChild?.scrollIntoView({ block: 'end' });
  } catch { /* non-fatal */ }
}

function _chatAppendMsg(role, contentEl) {
  const wrap = document.createElement('div');
  wrap.className = `chat-msg ${role}`;
  const avatar = document.createElement('div');
  avatar.className = 'chat-avatar';
  avatar.textContent = role === 'user' ? '👤' : '🤖';
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.appendChild(contentEl);
  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  document.getElementById('chat-messages').appendChild(wrap);
  wrap.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return bubble;
}

function _chatTypingIndicator() {
  const el = document.createElement('div');
  el.className = 'chat-typing';
  el.innerHTML = '<span></span><span></span><span></span>';
  const bubble = _chatAppendMsg('assistant', el);
  return bubble;
}

async function sendChatMessage() {
  if (_chatStreaming) return;
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';

  // Show user message
  const userEl = document.createElement('span');
  userEl.textContent = text;
  _chatAppendMsg('user', userEl);

  _chatMessages.push({ role: 'user', content: text });
  _chatStreaming = true;
  document.getElementById('chat-send-btn').disabled = true;

  const typingBubble = _chatTypingIndicator();

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: _chatMessages, conversation_id: _currentConvId, mode: _wikiInterviewMode ? 'wiki_interview' : 'normal' }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || resp.statusText);
    }

    // Replace typing indicator with real content
    typingBubble.innerHTML = '';
    const textNode = document.createElement('div');
    typingBubble.appendChild(textNode);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    let toolCalls = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === 'text') {
          fullText += evt.text;
          textNode.innerHTML = _md(fullText);
          typingBubble.parentElement?.scrollIntoView({ behavior: 'smooth', block: 'end' });
        } else if (evt.type === 'tool_call') {
          const pill = document.createElement('div');
          pill.className = 'chat-tool-call';
          pill.dataset.tool = evt.tool;
          pill.innerHTML = `⚙️ ${escHtml(_toolLabel(evt.tool, evt.input))}…`;
          typingBubble.insertBefore(pill, textNode);
          toolCalls.push({ pill, tool: evt.tool });
        } else if (evt.type === 'tool_result') {
          const pill = toolCalls.find(t => t.tool === evt.tool);
          if (pill) { pill.pill.classList.add('done'); pill.pill.innerHTML = `✓ ${escHtml(_toolLabel(evt.tool, {}))}`; }
        } else if (evt.type === 'error') {
          typingBubble.innerHTML = '';
          const errEl = document.createElement('div');
          errEl.className = 'chat-error-msg';
          errEl.innerHTML = _md(evt.message);
          typingBubble.appendChild(errEl);
          break;
        } else if (evt.type === 'usage') {
          const usageEl = document.createElement('div');
          usageEl.className = 'chat-usage';
          const costStr = evt.cost_usd < 0.001
            ? `< $0.001`
            : `~$${evt.cost_usd.toFixed(4)}`;
          usageEl.textContent = `↑${evt.input_tokens.toLocaleString()} ↓${evt.output_tokens.toLocaleString()} tokens · ${costStr}`;
          typingBubble.appendChild(usageEl);
        } else if (evt.type === 'done') {
          break;
        }
      }
    }

    _chatMessages.push({ role: 'assistant', content: fullText });
    // Refresh conversation list (title may have been auto-set on first message)
    api('GET', '/api/chat/conversations').then(convs => _renderConvList(convs)).catch(() => {});
  } catch (e) {
    typingBubble.innerHTML = `<span style="color:var(--offline)">Error: ${escHtml(e.message)}</span>`;
  } finally {
    _chatStreaming = false;
    document.getElementById('chat-send-btn').disabled = false;
  }
}

function _toolLabel(tool, input) {
  const labels = {
    get_servers_status:      'Checking server status',
    get_printers_status:     'Checking printer status',
    ping_device:             `Pinging ${input?.ip || 'device'}`,
    restart_server:          `Restarting ${input?.ip || 'server'}`,
    get_printer_install_link:`Getting installer for ${input?.ip || 'printer'}`,
    search_wiki:             `Searching wiki: ${input?.query || ''}`,
    get_wiki_article:        `Reading wiki article`,
    create_wiki_category:    `Creating category: ${input?.name || ''}`,
    create_wiki_article:     `Saving article: ${input?.title || ''}`,
    update_wiki_article:     `Updating article: ${input?.title || ''}`,
  };
  return labels[tool] || tool;
}

// Wire up send button and Enter key
document.getElementById('chat-send-btn').addEventListener('click', sendChatMessage);
document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
});
// Auto-resize textarea
document.getElementById('chat-input').addEventListener('input', function () {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});

// ---- Service Worker & Offline ----
let _offlineSince = null;

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(e => console.warn('SW:', e));
  navigator.serviceWorker.addEventListener('message', e => {
    if (e.data?.type === 'offline_cache_hit') _showOfflineBanner(true);
  });
}

function _showOfflineBanner(offline) {
  const banner = document.getElementById('offline-banner');
  const since  = document.getElementById('offline-since');
  if (!banner) return;
  if (offline) {
    _offlineSince = _offlineSince || Date.now();
    if (since) {
      const mins = Math.round((Date.now() - _offlineSince) / 60000);
      since.textContent = mins > 0 ? ` · ${mins}min ago` : '';
    }
    banner.classList.remove('hidden');
    document.body.classList.add('is-offline');
  } else {
    _offlineSince = null;
    banner.classList.add('hidden');
    document.body.classList.remove('is-offline');
  }
}

window.addEventListener('offline', () => _showOfflineBanner(true));

// ======== Workstations module ========
let _wsCenters      = [];
let _wsCurrentId    = null;  // selected center id
let _wsEditing      = null;  // editing workstation id
let _wsCenterEditing = null; // editing center id
let _wsPingStatus   = {};    // {ip: true/false}

async function loadWorkstations() {
  try {
    _wsCenters = await api('GET', '/api/workstations/centers');
    _renderCenterTabs();
    // Select first center by default if none selected
    if (!_wsCurrentId && _wsCenters.length) {
      _wsCurrentId = _wsCenters[0].id;
      _renderCenterTabs();
    }
    await _loadWsGrid();
  } catch (e) {
    toast(`Workstations load failed: ${e.message}`, 'err');
  }
}

function _renderCenterTabs() {
  const tabs = document.getElementById('ws-center-tabs');
  tabs.innerHTML = '';
  _wsCenters.forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'ws-tab-btn' + (c.id === _wsCurrentId ? ' active' : '');
    btn.innerHTML = `${escHtml(c.name)} <span class="ws-tab-count">${c.workstation_count}</span>`;
    btn.addEventListener('click', async () => {
      _wsCurrentId = c.id;
      _wsPingStatus = {};
      _renderCenterTabs();
      await _loadWsGrid();
    });
    if (state.isAdmin) {
      const editBtn = document.createElement('span');
      editBtn.className = 'ws-tab-edit';
      editBtn.title = 'Editar centro';
      editBtn.textContent = ' ✏️';
      editBtn.addEventListener('click', e => { e.stopPropagation(); _openCenterModal(c); });
      btn.appendChild(editBtn);
    }
    tabs.appendChild(btn);
  });
  if (!_wsCenters.length) {
    tabs.innerHTML = `<span class="text-dim">Sin centros. ${state.isAdmin ? 'Añade uno.' : ''}</span>`;
  }
}

async function _loadWsGrid() {
  const grid  = document.getElementById('ws-grid');
  const empty = document.getElementById('ws-empty');
  grid.innerHTML = '<span class="text-dim">Cargando…</span>';
  try {
    const params = _wsCurrentId ? `?center_id=${_wsCurrentId}` : '';
    const list   = await api('GET', `/api/workstations${params}`);
    grid.innerHTML = '';
    empty.classList.toggle('hidden', list.length > 0);
    list.forEach(ws => grid.appendChild(_buildWsCard(ws)));
  } catch (e) {
    grid.innerHTML = `<span class="text-dim">Error: ${escHtml(e.message)}</span>`;
  }
}

function _wsOsBadge(os) {
  const map = { windows: '🪟', linux: '🐧', macos: '🍎' };
  return map[os] || '🖥';
}

function _buildWsCard(ws) {
  const div = document.createElement('div');
  div.className = 'ws-card';
  const ping = _wsPingStatus[ws.ip];
  const dotCls   = ws.ip ? (ping === true ? 'online' : ping === false ? 'offline' : 'checking') : 'unknown';
  const dotLabel = !ws.ip ? 'Sin IP' : ping === true ? 'Online' : ping === false ? 'Offline' : '—';
  div.innerHTML = `
    <div class="ws-card-header">
      <span class="status-dot ${dotCls}"></span>
      <span class="ws-os-badge">${_wsOsBadge(ws.os_type)}</span>
      <div class="ws-card-name">${escHtml(ws.name)}</div>
      ${state.isAdmin ? `<button class="btn btn-sm ws-edit-btn" data-id="${ws.id}" title="Editar">✏️</button>` : ''}
    </div>
    <div class="ws-card-meta">
      ${ws.ip            ? `<span class="ws-meta-chip">🌐 ${escHtml(ws.ip)}</span>` : ''}
      ${ws.assigned_user ? `<span class="ws-meta-chip">👤 ${escHtml(ws.assigned_user)}</span>` : ''}
      ${ws.ram_gb        ? `<span class="ws-meta-chip">💾 ${ws.ram_gb} GB</span>` : ''}
      ${ws.cpu_model     ? `<span class="ws-meta-chip">🔲 ${escHtml(ws.cpu_model)}</span>` : ''}
      ${ws.disk_gb       ? `<span class="ws-meta-chip">💿 ${ws.disk_gb} GB</span>` : ''}
    </div>
    ${ws.notes ? `<div class="ws-card-notes text-dim">${escHtml(ws.notes)}</div>` : ''}
    <div class="ws-card-status text-dim">${dotLabel}</div>`;
  if (state.isAdmin) {
    div.querySelector('.ws-edit-btn').addEventListener('click', () => _openWsModal(ws));
  }
  return div;
}

async function _pingWorkstations() {
  const statusEl = document.getElementById('ws-ping-status');
  statusEl.textContent = 'Comprobando…';
  try {
    const params = _wsCurrentId ? `?center_id=${_wsCurrentId}` : '';
    const list   = await api('GET', `/api/workstations${params}`);
    const ips    = list.map(w => w.ip).filter(Boolean);
    if (!ips.length) { statusEl.textContent = 'Sin IPs configuradas'; return; }
    const results = await api('POST', '/api/workstations/ping', { ips });
    _wsPingStatus = results;
    statusEl.textContent = `${Object.values(results).filter(Boolean).length}/${ips.length} online`;
    const grid = document.getElementById('ws-grid');
    grid.innerHTML = '';
    list.forEach(ws => grid.appendChild(_buildWsCard(ws)));
  } catch (e) {
    statusEl.textContent = 'Error al comprobar';
  }
}

// Center modal
function _openCenterModal(center) {
  _wsCenterEditing = center ? center.id : null;
  document.getElementById('ws-center-modal-title').textContent = center ? 'Editar centro' : 'Nuevo centro';
  document.getElementById('wscm-name').value     = center?.name     || '';
  document.getElementById('wscm-location').value = center?.location || '';
  const delBtn = document.getElementById('ws-center-modal-delete');
  if (center && state.isAdmin) delBtn.classList.remove('hidden');
  else delBtn.classList.add('hidden');
  document.getElementById('ws-center-modal').classList.remove('hidden');
}

async function _saveCenterModal() {
  const name     = document.getElementById('wscm-name').value.trim();
  const location = document.getElementById('wscm-location').value.trim();
  if (!name) { toast('El nombre es obligatorio', 'err'); return; }
  try {
    if (_wsCenterEditing) {
      await api('PUT', `/api/workstations/centers/${_wsCenterEditing}`, { name, location });
      toast('Centro actualizado', 'ok');
    } else {
      const res = await api('POST', '/api/workstations/centers', { name, location });
      _wsCurrentId = res.id;
      toast('Centro creado', 'ok');
    }
    document.getElementById('ws-center-modal').classList.add('hidden');
    await loadWorkstations();
  } catch (e) { toast(`Error: ${e.message}`, 'err'); }
}

async function _deleteCenterModal() {
  if (!_wsCenterEditing) return;
  const c = _wsCenters.find(x => x.id === _wsCenterEditing);
  if (!confirm(`¿Eliminar centro "${c?.name}"? Se eliminarán todos sus equipos.`)) return;
  try {
    await api('DELETE', `/api/workstations/centers/${_wsCenterEditing}`);
    _wsCurrentId = null;
    document.getElementById('ws-center-modal').classList.add('hidden');
    toast('Centro eliminado', 'ok');
    await loadWorkstations();
  } catch (e) { toast(`Error: ${e.message}`, 'err'); }
}

// Workstation modal
function _openWsModal(ws) {
  _wsEditing = ws ? ws.id : null;
  document.getElementById('ws-wm-title').textContent = ws ? 'Editar equipo' : 'Nuevo equipo';
  document.getElementById('wswm-name').value  = ws?.name          || '';
  document.getElementById('wswm-ip').value    = ws?.ip            || '';
  document.getElementById('wswm-os').value    = ws?.os_type       || 'windows';
  document.getElementById('wswm-user').value  = ws?.assigned_user || '';
  document.getElementById('wswm-ram').value   = ws?.ram_gb  != null ? ws.ram_gb  : '';
  document.getElementById('wswm-cpu').value   = ws?.cpu_model     || '';
  document.getElementById('wswm-disk').value  = ws?.disk_gb != null ? ws.disk_gb : '';
  document.getElementById('wswm-notes').value = ws?.notes         || '';
  const delBtn = document.getElementById('ws-wm-delete');
  if (ws && state.isAdmin) delBtn.classList.remove('hidden'); else delBtn.classList.add('hidden');
  document.getElementById('ws-workstation-modal').classList.remove('hidden');
}

async function _saveWsModal() {
  const name = document.getElementById('wswm-name').value.trim();
  if (!name) { toast('El nombre es obligatorio', 'err'); return; }
  if (!_wsCurrentId && !_wsEditing) { toast('Selecciona un centro primero', 'err'); return; }
  const body = {
    center_id:     _wsCurrentId,
    name,
    ip:            document.getElementById('wswm-ip').value.trim()   || null,
    os_type:       document.getElementById('wswm-os').value,
    assigned_user: document.getElementById('wswm-user').value.trim() || null,
    ram_gb:        parseInt(document.getElementById('wswm-ram').value)  || null,
    cpu_model:     document.getElementById('wswm-cpu').value.trim()  || null,
    disk_gb:       parseInt(document.getElementById('wswm-disk').value) || null,
    notes:         document.getElementById('wswm-notes').value.trim() || null,
  };
  try {
    if (_wsEditing) {
      await api('PUT', `/api/workstations/${_wsEditing}`, body);
      toast('Equipo actualizado', 'ok');
    } else {
      await api('POST', '/api/workstations', body);
      toast('Equipo añadido', 'ok');
    }
    document.getElementById('ws-workstation-modal').classList.add('hidden');
    await _loadWsGrid();
    _wsCenters = await api('GET', '/api/workstations/centers');
    _renderCenterTabs();
  } catch (e) { toast(`Error: ${e.message}`, 'err'); }
}

async function _deleteWsModal() {
  if (!_wsEditing) return;
  if (!confirm('¿Eliminar este equipo?')) return;
  try {
    await api('DELETE', `/api/workstations/${_wsEditing}`);
    document.getElementById('ws-workstation-modal').classList.add('hidden');
    toast('Equipo eliminado', 'ok');
    await _loadWsGrid();
    _wsCenters = await api('GET', '/api/workstations/centers');
    _renderCenterTabs();
  } catch (e) { toast(`Error: ${e.message}`, 'err'); }
}

// Wire up all workstation button event listeners
document.getElementById('ws-refresh-btn').addEventListener('click', _pingWorkstations);
document.getElementById('ws-add-center-btn').addEventListener('click', () => _openCenterModal(null));
document.getElementById('ws-add-workstation-btn').addEventListener('click', () => {
  if (!_wsCurrentId) { toast('Selecciona un centro primero', 'err'); return; }
  _openWsModal(null);
});
document.getElementById('ws-center-modal-close').addEventListener('click',  () => document.getElementById('ws-center-modal').classList.add('hidden'));
document.getElementById('ws-center-modal-cancel').addEventListener('click', () => document.getElementById('ws-center-modal').classList.add('hidden'));
document.getElementById('ws-center-modal-save').addEventListener('click',   _saveCenterModal);
document.getElementById('ws-center-modal-delete').addEventListener('click', _deleteCenterModal);
document.getElementById('ws-wm-close').addEventListener('click',   () => document.getElementById('ws-workstation-modal').classList.add('hidden'));
document.getElementById('ws-wm-cancel').addEventListener('click',  () => document.getElementById('ws-workstation-modal').classList.add('hidden'));
document.getElementById('ws-wm-save').addEventListener('click',    _saveWsModal);
document.getElementById('ws-wm-delete').addEventListener('click',  _deleteWsModal);
window.addEventListener('online',  () => { _showOfflineBanner(false); location.reload(); });
