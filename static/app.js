/**
 * Visual Dashboard Client Application
 * Handles real-time SSE log streaming, pipeline controls, interactive flowchart highlights,
 * job applications table, target registry editor, master resume editor, and modal previews.
 */

let allJobsData = [];
let currentFilter = 'all';
let currentSearch = '';
let activeStage = null;
let eventSource = null;
let allContacts = [];
let contactStatuses = {};
let outreachSettings = {};
let contactSearch = '';
let editingContactId = null;
let cvView = 'editor';

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  initSSE();
  fetchStatus();
  loadJobsList();
  loadGallery();
  loadTargetsConfig();
  loadMasterResume();
  loadCv();
  loadContacts();

  // Poll system status every 3 seconds
  setInterval(fetchStatus, 3000);
});

// ---------------------------------------------------------------------------
// Tab Navigation
// ---------------------------------------------------------------------------
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));

  const activeBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => 
    b.getAttribute('onclick') && b.getAttribute('onclick').includes(tabId)
  );
  if (activeBtn) activeBtn.classList.add('active');

  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) targetTab.classList.add('active');

  if (tabId === 'jobs') loadJobsList();
  if (tabId === 'gallery') loadGallery();
  if (tabId === 'targets') loadTargetsConfig();
  if (tabId === 'resume') loadMasterResume();
  if (tabId === 'portfolio') loadCv();
  if (tabId === 'outreach') {
    loadContacts();
    populateJobSelect();
  }
}

// ---------------------------------------------------------------------------
// Real-Time System Status & Metrics
// ---------------------------------------------------------------------------
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    const p = data.pipeline || {};
    const stats = data.stats || {};
    const env = data.environment || {};

    // Update Status Pill
    const pill = document.getElementById('pipeline-status-pill');
    const pillText = document.getElementById('pipeline-status-text');
    const stepText = document.getElementById('pipeline-step-text');
    const daemonBtn = document.getElementById('daemon-btn-label');
    const stopBtn = document.getElementById('btn-stop-run');

    pill.className = `status-pill ${p.status || 'idle'}`;
    pillText.textContent = (p.status || 'IDLE').toUpperCase();
    stepText.textContent = p.current_step || 'System Ready';

    if (p.status === 'daemon') {
      daemonBtn.textContent = 'Stop Daemon';
      stopBtn.style.display = 'none';
    } else {
      daemonBtn.textContent = 'Start Background Daemon';
      stopBtn.style.display = (p.status === 'running') ? 'inline-flex' : 'none';
    }

    // Disable/enable run buttons based on state
    const isBusy = p.status === 'running' || p.status === 'daemon';
    document.getElementById('btn-run-once').disabled = isBusy;
    document.getElementById('btn-run-mock').disabled = isBusy;

    // Update Metrics
    document.getElementById('metric-total-jobs').textContent = stats.total || 0;
    document.getElementById('metric-tailored').textContent = stats.tailored || 0;
    document.getElementById('metric-applied').textContent = stats.applied || 0;
    document.getElementById('metric-flagged').textContent = stats.failed || 0;
    
    document.getElementById('tab-jobs-count').textContent = stats.total || 0;
    document.getElementById('tab-gallery-count').textContent = (data.counts && data.counts.screenshots_captured) || 0;

    // Update Environment Health Badges
    updateEnvBadge('env-llm', env.gemini_api_key || env.openai_api_key, 'Gemini / OpenAI API Configured');
    updateEnvBadge('env-sheet', env.google_sheet_configured || env.service_account_exists, 'Google Sheets Linked');
    updateEnvBadge('env-auto-submit', env.auto_submit_enabled, 'Auto-Submit Active');
    updateEnvBadge('env-email', env.smtp_configured, 'SMTP Email Sending');

    // Candidate identity comes from cv.json
    const candidate = data.candidate || {};
    if (candidate.name) {
      document.getElementById('candidate-name').textContent = candidate.name;
      document.getElementById('candidate-avatar').textContent =
        candidate.name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
    }
    if (candidate.role) document.getElementById('candidate-role').textContent = candidate.role;

    updateOutreachControls(data.outreach || {});

    // Highlight Architecture Flow Node based on step
    highlightFlowNodeByStep(p.current_step || '');

  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

function updateEnvBadge(id, isActive, title) {
  const el = document.getElementById(id);
  if (!el) return;
  if (isActive) {
    el.classList.add('active');
    el.title = `${title}: Connected`;
  } else {
    el.classList.remove('active');
    el.title = `${title}: Not Configured (Using Local Fallback)`;
  }
}

// ---------------------------------------------------------------------------
// Interactive Flowchart Highlighting
// ---------------------------------------------------------------------------
function highlightFlowNodeByStep(stepText) {
  const s = stepText.toLowerCase();
  clearFlowHighlights();

  if (s.includes('scraping') || s.includes('target') || s.includes('discovery')) {
    setFlowNodeActive('flow-node-scrape');
  } else if (s.includes('dedup') || s.includes('checking sheet') || s.includes('evaluating')) {
    setFlowNodeActive('flow-node-dedup');
  } else if (s.includes('tailor') || s.includes('llm') || s.includes('gemini') || s.includes('pdf')) {
    setFlowNodeActive('flow-node-llm');
  } else if (s.includes('apply') || s.includes('playwright') || s.includes('submit')) {
    setFlowNodeActive('flow-node-apply');
  } else if (s.includes('audit') || s.includes('logging') || s.includes('screenshot') || s.includes('saving')) {
    setFlowNodeActive('flow-node-audit');
  }
}

function clearFlowHighlights() {
  document.querySelectorAll('.flow-node').forEach(n => n.classList.remove('active-stage'));
}

function setFlowNodeActive(nodeId) {
  const el = document.getElementById(nodeId);
  if (el) el.classList.add('active-stage');
}

// ---------------------------------------------------------------------------
// Real-Time Server-Sent Events (SSE) Console Stream
// ---------------------------------------------------------------------------
function initSSE() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource('/api/logs/stream');

  eventSource.onmessage = (event) => {
    try {
      const log = JSON.parse(event.data);
      appendLogToConsole(log);
    } catch (e) {
      // heartbeats or ping
    }
  };

  eventSource.onerror = () => {
    // Reconnect will happen automatically by the browser EventSource
  };
}

function appendLogToConsole(log) {
  const consoleBody = document.getElementById('console-stream');
  if (!consoleBody) return;

  const entry = document.createElement('div');
  entry.className = 'log-entry';

  // Format message text with colored tags
  let msg = escapeHtml(log.message || log.formatted || '');
  msg = msg.replace(/\[LLM\]/g, '<span class="tag-llm">[LLM]</span>');
  msg = msg.replace(/\[APPLY\]/g, '<span class="tag-apply">[APPLY]</span>');
  msg = msg.replace(/\[AUDIT\]/g, '<span class="tag-audit">[AUDIT]</span>');
  msg = msg.replace(/\[SKIP\]/g, '<span class="tag-skip">[SKIP]</span>');
  msg = msg.replace(/\[EMAIL\]/g, '<span class="tag-email">[EMAIL]</span>');
  msg = msg.replace(/\[OK\]/g, '<span style="color: #34d399; font-weight: bold;">[OK]</span>');
  msg = msg.replace(/\[LOG\]/g, '<span style="color: #60a5fa; font-weight: bold;">[LOG]</span>');

  entry.innerHTML = `
    <span class="log-time">${log.timestamp || '--:--:--'}</span>
    <span class="log-badge ${log.level || 'INFO'}">${log.level || 'INFO'}</span>
    <span class="log-msg">${msg}</span>
  `;

  consoleBody.appendChild(entry);

  // Auto-scroll if enabled
  const autoScroll = document.getElementById('chk-autoscroll').checked;
  if (autoScroll) {
    consoleBody.scrollTop = consoleBody.scrollHeight;
  }

  // Cap console DOM entries
  while (consoleBody.children.length > 500) {
    consoleBody.removeChild(consoleBody.firstChild);
  }
}

function clearConsole() {
  const consoleBody = document.getElementById('console-stream');
  if (consoleBody) {
    consoleBody.innerHTML = `
      <div class="log-entry">
        <span class="log-time">--:--:--</span>
        <span class="log-badge INFO">INFO</span>
        <span class="log-msg">Terminal console cleared by user.</span>
      </div>
    `;
  }
}

// ---------------------------------------------------------------------------
// Pipeline Execution Actions
// ---------------------------------------------------------------------------
async function triggerRun(mode) {
  const autoSubmit = document.getElementById('chk-auto-submit').checked;
  const headless = document.getElementById('chk-headless').checked;

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: mode,
        auto_submit: autoSubmit,
        headless: headless,
        min_delay: mode === 'mock' ? 1 : 15,
        max_delay: mode === 'mock' ? 3 : 45
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(`Started ${mode.toUpperCase()} pipeline execution.`, 'success');
      fetchStatus();
    } else {
      showToast(data.message || 'Failed to start pipeline.', 'error');
    }
  } catch (err) {
    showToast(`Error triggering run: ${err}`, 'error');
  }
}

async function triggerDirectUrl() {
  const urlInput = document.getElementById('input-direct-url');
  const targetUrl = (urlInput.value || '').trim();

  if (!targetUrl || !targetUrl.startsWith('http')) {
    showToast('Please provide a valid HTTP/HTTPS job posting URL.', 'error');
    return;
  }

  const autoSubmit = document.getElementById('chk-auto-submit').checked;
  const headless = document.getElementById('chk-headless').checked;

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'url',
        url: targetUrl,
        auto_submit: autoSubmit,
        headless: headless,
        max_jobs: 1,
        min_delay: 5,
        max_delay: 15
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(`Started pipeline targeting: ${targetUrl}`, 'success');
      fetchStatus();
    } else {
      showToast(data.message || 'Failed to trigger URL pipeline.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

async function stopRun() {
  try {
    const res = await fetch('/api/stop', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'Run stop requested.', 'success');
    fetchStatus();
  } catch (err) {
    showToast(`Failed to stop run: ${err}`, 'error');
  }
}

async function toggleDaemon() {
  const statusRes = await fetch('/api/status');
  const statusData = await statusRes.json();
  const isDaemon = (statusData.pipeline && statusData.pipeline.status === 'daemon');

  if (isDaemon) {
    // Stop daemon
    const res = await fetch('/api/daemon/stop', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'Daemon stopped.', 'success');
  } else {
    // Start daemon
    const interval = parseInt(document.getElementById('input-daemon-interval').value || '60', 10);
    const autoSubmit = document.getElementById('chk-auto-submit').checked;
    const headless = document.getElementById('chk-headless').checked;

    const res = await fetch('/api/daemon/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_minutes: interval,
        use_mock: false,
        auto_submit: autoSubmit,
        headless: headless
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Background Daemon started (${interval}m interval).`, 'success');
    } else {
      showToast(data.message || 'Failed to start daemon.', 'error');
    }
  }
  fetchStatus();
}

// ---------------------------------------------------------------------------
// Jobs Table & State Management
// ---------------------------------------------------------------------------
async function loadJobsList() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return;
    const data = await res.json();
    allJobsData = data.jobs || [];
    renderJobsTable();
  } catch (err) {
    console.error('Failed to load jobs:', err);
  }
}

function filterJobs(filter) {
  currentFilter = filter;
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
  const activePill = Array.from(document.querySelectorAll('.filter-pill')).find(p => 
    p.getAttribute('onclick') && p.getAttribute('onclick').includes(filter)
  );
  if (activePill) activePill.classList.add('active');
  renderJobsTable();
}

function searchJobs(query) {
  currentSearch = (query || '').toLowerCase().trim();
  renderJobsTable();
}

function renderJobsTable() {
  const tbody = document.getElementById('jobs-table-body');
  if (!tbody) return;

  // Filter & Search
  let filtered = allJobsData.filter(job => {
    const status = (job.status || '').toLowerCase();
    if (currentFilter === 'applied' && !status.includes('applied')) return false;
    if (currentFilter === 'tailored' && !status.includes('tailored')) return false;
    if (currentFilter === 'pending' && !status.includes('pending')) return false;
    if (currentFilter === 'failed' && !(status.includes('failed') || status.includes('manual'))) return false;

    if (currentSearch) {
      const matchTitle = (job.title || '').toLowerCase().includes(currentSearch);
      const matchComp = (job.company || '').toLowerCase().includes(currentSearch);
      const matchUrl = (job.job_url || '').toLowerCase().includes(currentSearch);
      if (!matchTitle && !matchComp && !matchUrl) return false;
    }
    return true;
  });

  // Update counts on filter pills
  const countAll = allJobsData.length;
  const countApplied = allJobsData.filter(j => (j.status || '').toLowerCase().includes('applied')).length;
  const countTailored = allJobsData.filter(j => (j.status || '').toLowerCase().includes('tailored')).length;
  const countPending = allJobsData.filter(j => (j.status || '').toLowerCase().includes('pending')).length;
  const countFailed = allJobsData.filter(j => {
    const s = (j.status || '').toLowerCase();
    return s.includes('failed') || s.includes('manual');
  }).length;

  document.getElementById('count-all').textContent = countAll;
  document.getElementById('count-applied').textContent = countApplied;
  document.getElementById('count-tailored').textContent = countTailored;
  document.getElementById('count-pending').textContent = countPending;
  document.getElementById('count-failed').textContent = countFailed;

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">
          No matching applications found. Run a single pass or mock test to populate.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(job => {
    const statusClass = getStatusClass(job.status);
    const pdfBtn = job.pdf_url ? `
      <button class="btn btn-outline" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="openPdfModal('${job.pdf_url}', '${escapeHtml(job.title)}')">
        📄 View PDF
      </button>
    ` : '<span style="color: var(--text-muted); font-size: 0.75rem;">No PDF</span>';

    const screenshotBtn = job.screenshot_url ? `
      <button class="btn btn-outline" style="padding: 0.25rem 0.55rem; font-size: 0.72rem;" onclick="openScreenshotModal('${job.screenshot_url}', '${escapeHtml(job.company)} - ${escapeHtml(job.title)}')">
        🖼️ Screenshot
      </button>
    ` : '';

    return `
      <tr>
        <td style="color: var(--text-muted); font-size: 0.75rem;">${escapeHtml(job.date_found || 'Recently')}</td>
        <td>
          <div style="font-weight: 700; color: var(--text-primary);">${escapeHtml(job.title)}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(job.company)}</div>
        </td>
        <td>
          <span style="font-weight: 600;">${escapeHtml(job.company)}</span>
        </td>
        <td>
          <a href="${escapeHtml(job.job_url)}" target="_blank" rel="noopener" style="color: var(--color-brand); text-decoration: none; font-size: 0.78rem; word-break: break-all;">
            ${escapeHtml(truncateUrl(job.job_url))} ↗
          </a>
        </td>
        <td>
          <span class="status-tag ${statusClass}">
            ● ${escapeHtml(job.status || 'Pending')}
          </span>
        </td>
        <td>
          <div style="display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
            ${pdfBtn}
            ${screenshotBtn}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function getStatusClass(status) {
  const s = (status || '').toLowerCase();
  if (s.includes('applied')) return 'applied';
  if (s.includes('tailored')) return 'tailored';
  if (s.includes('pending')) return 'pending';
  if (s.includes('failed') || s.includes('manual')) return 'failed';
  return 'pending';
}

function truncateUrl(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    return u.hostname + u.pathname.substring(0, 24) + (u.pathname.length > 24 ? '...' : '');
  } catch (e) {
    return url.substring(0, 32) + '...';
  }
}

// ---------------------------------------------------------------------------
// Visual Audit Screenshots Gallery
// ---------------------------------------------------------------------------
async function loadGallery() {
  try {
    const res = await fetch('/api/screenshots');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('gallery-container');
    if (!container) return;

    const list = data.screenshots || [];
    if (list.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 3rem;">
          No audit screenshots captured yet. Screenshots are saved automatically when <code>apply_bot.py</code> submits applications.
        </div>
      `;
      return;
    }

    container.innerHTML = list.map(item => `
      <div class="gallery-card">
        <div class="gallery-thumb" onclick="openScreenshotModal('${item.url}', '${escapeHtml(item.filename)}')">
          <img src="${item.url}" alt="${escapeHtml(item.filename)}" loading="lazy">
        </div>
        <div class="gallery-info">
          <div class="gallery-name" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</div>
          <div class="gallery-meta">Captured: ${escapeHtml(item.timestamp)} (${item.size_kb} KB)</div>
          <div style="margin-top: 0.4rem;">
            <button class="btn btn-outline" style="width: 100%; padding: 0.25rem; font-size: 0.72rem;" onclick="openScreenshotModal('${item.url}', '${escapeHtml(item.filename)}')">
              View Full Size
            </button>
          </div>
        </div>
      </div>
    `).join('');

  } catch (err) {
    console.error('Failed to load gallery:', err);
  }
}

// ---------------------------------------------------------------------------
// Targets Registry Configuration Editor
// ---------------------------------------------------------------------------
async function loadTargetsConfig() {
  try {
    const res = await fetch('/api/targets');
    if (!res.ok) return;
    const data = await res.json();
    const textarea = document.getElementById('textarea-targets-json');
    if (textarea) {
      textarea.value = JSON.stringify(data, null, 2);
    }
  } catch (err) {
    console.error('Failed to load targets:', err);
  }
}

async function saveTargetsConfig() {
  const textarea = document.getElementById('textarea-targets-json');
  try {
    const parsed = JSON.parse(textarea.value);
    const res = await fetch('/api/targets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(parsed)
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Targets configuration saved successfully.', 'success');
      fetchStatus();
    } else {
      showToast(data.detail || 'Failed to save targets configuration.', 'error');
    }
  } catch (e) {
    showToast(`Invalid JSON: ${e.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Master Resume Editor
// ---------------------------------------------------------------------------
async function loadMasterResume() {
  try {
    const res = await fetch('/api/resume');
    if (!res.ok) return;
    const data = await res.json();
    const textarea = document.getElementById('textarea-resume-md');
    if (textarea) {
      textarea.value = data.content || '';
    }
  } catch (err) {
    console.error('Failed to load master resume:', err);
  }
}

async function saveMasterResume() {
  const textarea = document.getElementById('textarea-resume-md');
  const content = textarea.value;

  try {
    const res = await fetch('/api/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Master resume updated successfully.', 'success');
    } else {
      showToast(data.detail || 'Failed to update master resume.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Portfolio & Structured CV Editor
// ---------------------------------------------------------------------------
let cvDirty = false;

async function loadCv() {
  try {
    const res = await fetch('/api/cv');
    if (!res.ok) return;
    const data = await res.json();
    const textarea = document.getElementById('textarea-cv-json');
    if (textarea && !cvDirty) {
      textarea.value = JSON.stringify(data.cv, null, 2);
      textarea.oninput = () => { cvDirty = true; };
    }
    document.getElementById('portfolio-built-at').textContent = data.built_at || 'Never';
    document.getElementById('portfolio-pdf-link').style.display = data.pdf_url ? '' : 'none';
  } catch (err) {
    console.error('Failed to load CV:', err);
  }
}

async function saveCv() {
  const textarea = document.getElementById('textarea-cv-json');
  let parsed;
  try {
    parsed = JSON.parse(textarea.value);
  } catch (e) {
    showToast(`Invalid JSON: ${e.message}`, 'error');
    return;
  }

  showToast('Saving CV and rebuilding the portfolio...', 'info');
  try {
    const res = await fetch('/api/cv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cv: parsed })
    });
    const data = await res.json();
    if (res.ok) {
      cvDirty = false;
      showToast('CV saved. Portfolio and CV PDF rebuilt.', 'success');
      loadCv();
      refreshPortfolioPreview();
      fetchStatus();
    } else {
      showToast(formatDetail(data.detail) || 'Failed to save CV.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

async function syncMasterResume() {
  if (!confirm('Replace master_resume.md with the content of cv.json? Resume tailoring uses master_resume.md as its source of truth.')) return;
  try {
    const res = await fetch('/api/cv/sync-master', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message, 'success');
      loadMasterResume();
    } else {
      showToast(formatDetail(data.detail) || 'Failed to sync master resume.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

function setCvView(view) {
  cvView = view;
  document.getElementById('textarea-cv-json').style.display = view === 'editor' ? '' : 'none';
  document.getElementById('portfolio-preview').style.display = view === 'preview' ? '' : 'none';
  document.getElementById('seg-cv-editor').classList.toggle('active', view === 'editor');
  document.getElementById('seg-cv-preview').classList.toggle('active', view === 'preview');
  refreshPortfolioPreview();
}

function refreshPortfolioPreview() {
  if (cvView !== 'preview') return;
  document.getElementById('portfolio-preview').src = `/portfolio/?t=${Date.now()}`;
}

// ---------------------------------------------------------------------------
// Cold Outreach: Contacts, Drafts & Automation
// ---------------------------------------------------------------------------
const CONTACT_STATUS_CLASS = {
  new: 'pending',
  drafted: 'tailored',
  previewed: 'tailored',
  sent: 'applied',
  followed_up: 'applied',
  replied: 'replied',
  failed: 'failed',
  do_not_contact: 'muted',
};

let outreachAutoSendInitialized = false;
let currentOutreachStatus = 'idle';

async function loadContacts() {
  try {
    const res = await fetch('/api/contacts');
    const data = await res.json();
    if (!res.ok) {
      showToast(formatDetail(data.detail) || 'Failed to load contacts.', 'error');
      return;
    }
    allContacts = data.contacts || [];
    contactStatuses = data.statuses || {};
    outreachSettings = Object.assign({}, data.settings || {}, { opt_out_line: data.opt_out_line });

    if (!outreachAutoSendInitialized) {
      document.getElementById('chk-outreach-auto-send').checked = !!outreachSettings.auto_send;
      outreachAutoSendInitialized = true;
    }
    renderOutreachMetrics(data.stats || {});
    renderModeBanner();
    renderContactsTable();
  } catch (err) {
    console.error('Failed to load contacts:', err);
  }
}

function renderOutreachMetrics(stats) {
  const emailed = (stats.sent || 0) + (stats.followed_up || 0) + (stats.replied || 0);
  const replies = stats.replied || 0;
  document.getElementById('metric-contacts').textContent = stats.total || 0;
  document.getElementById('metric-drafts').textContent = (stats.drafted || 0) + (stats.previewed || 0);
  document.getElementById('metric-sent').textContent = emailed;
  document.getElementById('metric-sent-today').textContent =
    `${stats.sent_today || 0} today · limit ${outreachSettings.daily_limit || 0}/day`;
  document.getElementById('metric-replies').textContent = replies;
  document.getElementById('metric-reply-rate').textContent =
    emailed ? `Reply rate: ${Math.round((replies / emailed) * 100)}%` : 'Reply rate: n/a';
  document.getElementById('tab-outreach-count').textContent = stats.total || 0;
}

function renderModeBanner() {
  const banner = document.getElementById('outreach-mode-banner');
  const s = outreachSettings;
  if (s.dry_run) {
    banner.className = 'mode-banner dry';
    banner.innerHTML = s.smtp_configured
      ? `<strong>Dry run: nothing is sent</strong>SMTP is set up for ${escapeHtml(s.smtp_user)}. Set <code>EMAIL_DRY_RUN=false</code> in <code>.env</code> and restart to send for real.`
      : `<strong>Dry run: nothing is sent</strong>Emails are saved as previews in <code>output/emails/</code>. Add <code>SMTP_USER</code> and <code>SMTP_APP_PASSWORD</code> to <code>.env</code> and set <code>EMAIL_DRY_RUN=false</code> to send for real.`;
  } else {
    banner.className = 'mode-banner live';
    banner.innerHTML = `<strong>Live: sending as ${escapeHtml(s.smtp_user)}</strong>Up to ${s.daily_limit} emails/day, ${s.max_followups} follow-up after ${s.followup_days} days. Stops as soon as someone replies.`;
  }
}

function searchContacts(query) {
  contactSearch = (query || '').toLowerCase().trim();
  renderContactsTable();
}

function renderContactsTable() {
  const tbody = document.getElementById('contacts-table-body');
  if (!tbody) return;

  const filtered = allContacts.filter(c => {
    if (!contactSearch) return true;
    return [c.name, c.email, c.company, c.role].some(v => (v || '').toLowerCase().includes(contactSearch));
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">
          ${allContacts.length ? 'No contacts match your search.' : 'No contacts yet. Add one on the left or import a CSV.'}
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(c => {
    const statusClass = CONTACT_STATUS_CLASS[c.status] || 'pending';
    const hasDraft = c.subject && c.body;
    const last = (c.history || []).slice(-1)[0];
    const activity = last
      ? `${historyLabel(last)} · ${formatWhen(last.at)}`
      : `Added · ${formatWhen(c.created_at)}`;
    const jobLink = c.job_url
      ? `<a href="${escapeHtml(c.job_url)}" target="_blank" rel="noopener" style="color: var(--color-brand); font-size: 0.72rem; text-decoration: none;">Linked job ↗</a>`
      : '';

    return `
      <tr>
        <td>
          <div style="font-weight: 700; color: var(--text-primary);">${escapeHtml(c.name || '(no name)')}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(c.email)}</div>
        </td>
        <td>
          <div style="font-weight: 600;">${escapeHtml(c.company || '—')}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(c.role || '')} ${jobLink}</div>
        </td>
        <td>
          <span class="status-tag ${statusClass}" title="${escapeHtml(c.last_error || '')}">● ${escapeHtml(contactStatuses[c.status] || c.status)}</span>
        </td>
        <td style="color: var(--text-muted); font-size: 0.75rem;">${escapeHtml(activity)}</td>
        <td>
          <div style="display: flex; gap: 0.4rem; flex-wrap: wrap;">
            <button class="btn btn-outline btn-xs" onclick="openEmailModal('${c.id}')">${hasDraft ? '✉️ View Email' : '✍️ Draft Email'}</button>
            <button class="btn btn-danger btn-xs" onclick="deleteContact('${c.id}')">Delete</button>
          </div>
        </td>
      </tr>`;
  }).join('');
}

function historyLabel(entry) {
  const kind = entry.kind === 'follow_up' || entry.type === 'follow_up' ? 'Follow-up' : 'Email';
  switch (entry.type) {
    case 'initial': return 'Email sent';
    case 'follow_up': return 'Follow-up sent';
    case 'preview': return `${kind} previewed`;
    case 'reply': return 'Reply received';
    case 'error': return `${kind} failed`;
    default: return entry.type;
  }
}

function formatWhen(iso) {
  if (!iso) return '';
  return iso.replace('T', ' ').substring(0, 16);
}

function formatDetail(detail) {
  if (!detail) return '';
  if (Array.isArray(detail)) return detail.map(d => d.msg || JSON.stringify(d)).join('; ');
  return String(detail);
}

async function populateJobSelect() {
  if (!allJobsData.length) await loadJobsList();
  const select = document.getElementById('contact-job');
  const current = select.value;
  select.innerHTML = '<option value="">None</option>' + allJobsData
    .filter(j => j.job_url)
    .map(j => `<option value="${escapeHtml(j.job_url)}">${escapeHtml(j.title)} · ${escapeHtml(j.company)}</option>`)
    .join('');
  select.value = current;
  select.onchange = () => {
    const job = allJobsData.find(j => j.job_url === select.value);
    if (!job) return;
    const company = document.getElementById('contact-company');
    const role = document.getElementById('contact-role');
    if (!company.value) company.value = job.company || '';
    if (!role.value) role.value = job.title || '';
  };
}

async function addContact() {
  const fields = ['name', 'email', 'company', 'role', 'notes'];
  const payload = {};
  fields.forEach(f => { payload[f] = document.getElementById(`contact-${f}`).value.trim(); });
  payload.job_url = document.getElementById('contact-job').value;

  if (!payload.email) {
    showToast('Email is required.', 'error');
    return;
  }

  try {
    const res = await fetch('/api/contacts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok) {
      fields.forEach(f => { document.getElementById(`contact-${f}`).value = ''; });
      document.getElementById('contact-job').value = '';
      showToast(`Added ${data.contact.name || data.contact.email}.`, 'success');
      loadContacts();
    } else {
      showToast(formatDetail(data.detail) || 'Failed to add contact.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

function loadCsvFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => { document.getElementById('textarea-csv').value = reader.result; };
  reader.readAsText(file);
}

async function importCsv() {
  const csvText = document.getElementById('textarea-csv').value.trim();
  if (!csvText) {
    showToast('Paste CSV text or choose a CSV file first.', 'error');
    return;
  }
  try {
    const res = await fetch('/api/contacts/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_text: csvText })
    });
    const data = await res.json();
    if (res.ok) {
      const skipped = data.skipped || [];
      const note = skipped.length ? ` Skipped ${skipped.length}: ${skipped.slice(0, 2).join(' ')}` : '';
      showToast(`Imported ${data.added} contact(s).${note}`, skipped.length && !data.added ? 'error' : 'success');
      document.getElementById('textarea-csv').value = '';
      document.getElementById('input-csv-file').value = '';
      loadContacts();
    } else {
      showToast(formatDetail(data.detail) || 'CSV import failed.', 'error');
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

async function deleteContact(contactId) {
  const contact = allContacts.find(c => c.id === contactId);
  if (!contact || !confirm(`Delete ${contact.name || contact.email} and their email history?`)) return;
  const res = await fetch(`/api/contacts/${contactId}`, { method: 'DELETE' });
  if (res.ok) {
    showToast('Contact deleted.', 'success');
    loadContacts();
  } else {
    showToast('Failed to delete contact.', 'error');
  }
}

async function openEmailModal(contactId) {
  let contact = allContacts.find(c => c.id === contactId);
  if (!contact) return;

  const alreadyEmailed = (contact.history || []).some(h => h.type === 'initial');
  if (!(contact.subject && contact.body) && !alreadyEmailed) {
    showToast(`Drafting email for ${contact.name || contact.email}...`, 'info');
    const res = await fetch(`/api/contacts/${contactId}/draft`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      showToast(formatDetail(data.detail) || 'Drafting failed.', 'error');
      return;
    }
    contact = data.contact;
    loadContacts();
  }

  editingContactId = contactId;
  fillEmailModal(contact);
  document.getElementById('email-modal').classList.add('open');
}

function fillEmailModal(contact) {
  const alreadyEmailed = (contact.history || []).some(h => h.type === 'initial');
  const closed = contact.status === 'replied' || contact.status === 'do_not_contact';
  const locked = alreadyEmailed || closed;

  document.getElementById('email-modal-title').textContent =
    `${alreadyEmailed ? 'Sent Email' : 'Email Draft'}: ${contact.name || contact.email}${contact.company ? ` (${contact.company})` : ''}`;
  document.getElementById('email-modal-to').textContent = contact.name ? `${contact.name} <${contact.email}>` : contact.email;

  const subject = document.getElementById('email-subject');
  const body = document.getElementById('email-body');
  subject.value = contact.subject || '';
  body.value = contact.body || '';
  subject.readOnly = alreadyEmailed;
  body.readOnly = alreadyEmailed;

  const sendBtn = document.getElementById('btn-email-send');
  sendBtn.textContent = outreachSettings.dry_run ? 'Save Preview (Dry Run)' : 'Send Now';
  sendBtn.disabled = locked;
  document.getElementById('btn-email-regenerate').disabled = locked;
  document.getElementById('btn-email-save').disabled = alreadyEmailed;

  document.getElementById('email-modal-footer-note').innerHTML = alreadyEmailed
    ? 'This email has been sent. Follow-ups go out automatically when the daemon runs with auto-send on.'
    : `The line <em>"${escapeHtml(outreachSettings.opt_out_line || '')}"</em> and your signature are added automatically, and your CV PDF is attached.`;

  const statusSelect = document.getElementById('email-status');
  statusSelect.innerHTML = Object.entries(contactStatuses)
    .map(([key, label]) => `<option value="${key}" ${key === contact.status ? 'selected' : ''}>Status: ${escapeHtml(label)}</option>`)
    .join('');

  document.getElementById('email-history').innerHTML = (contact.history || []).map(h => `
    <div class="email-history-item">
      <time>${escapeHtml(formatWhen(h.at))}</time>
      <span>${escapeHtml(historyLabel(h))}${h.subject ? `: ${escapeHtml(h.subject)}` : ''}${h.type === 'error' || h.type === 'preview' ? ` (${escapeHtml(h.detail || '')})` : ''}</span>
    </div>`).join('');
}

function closeEmailModal() {
  editingContactId = null;
  document.getElementById('email-modal').classList.remove('open');
}

async function saveEmailDraft(silent = false) {
  if (!editingContactId) return false;
  const res = await fetch(`/api/contacts/${editingContactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      subject: document.getElementById('email-subject').value,
      body: document.getElementById('email-body').value
    })
  });
  const data = await res.json();
  if (!res.ok) {
    showToast(formatDetail(data.detail) || 'Failed to save draft.', 'error');
    return false;
  }
  if (!silent) showToast('Draft saved.', 'success');
  loadContacts();
  return true;
}

async function regenerateDraft() {
  if (!editingContactId) return;
  if (!confirm('Replace the current draft with a newly generated one?')) return;
  showToast('Regenerating draft...', 'info');
  const res = await fetch(`/api/contacts/${editingContactId}/draft`, { method: 'POST' });
  const data = await res.json();
  if (res.ok) {
    fillEmailModal(data.contact);
    showToast('New draft generated.', 'success');
    loadContacts();
  } else {
    showToast(formatDetail(data.detail) || 'Drafting failed.', 'error');
  }
}

async function sendEmailNow() {
  if (!editingContactId) return;
  const contact = allContacts.find(c => c.id === editingContactId) || {};
  if (!outreachSettings.dry_run && !confirm(`Send this email to ${contact.email} now?`)) return;

  if (!(await saveEmailDraft(true))) return;
  const sendBtn = document.getElementById('btn-email-send');
  sendBtn.disabled = true;
  try {
    const res = await fetch(`/api/contacts/${editingContactId}/send`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message, 'success');
      closeEmailModal();
    } else {
      showToast(formatDetail(data.detail) || 'Sending failed.', 'error');
      sendBtn.disabled = false;
    }
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
    sendBtn.disabled = false;
  }
  loadContacts();
}

async function setContactStatus(status) {
  if (!editingContactId) return;
  const res = await fetch(`/api/contacts/${editingContactId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  const data = await res.json();
  if (res.ok) {
    showToast(`Status set to ${contactStatuses[status] || status}.`, 'success');
    fillEmailModal(data.contact);
    loadContacts();
  } else {
    showToast(formatDetail(data.detail) || 'Failed to update status.', 'error');
  }
}

function confirmLiveAutoSend(action) {
  if (outreachSettings.dry_run) return true;
  const ready = allContacts.filter(c => ['new', 'drafted', 'previewed'].includes(c.status)).length;
  return confirm(`${action} will email up to ${Math.min(ready, outreachSettings.daily_limit || ready)} contact(s) from ${outreachSettings.smtp_user} without review, plus any follow-ups that are due. Continue?`);
}

async function runOutreach() {
  const autoSend = document.getElementById('chk-outreach-auto-send').checked;
  if (autoSend && !confirmLiveAutoSend('This cycle')) return;
  try {
    const res = await fetch('/api/outreach/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_send: autoSend })
    });
    const data = await res.json();
    showToast(data.message || 'Outreach started.', res.ok ? 'success' : 'error');
    fetchStatus();
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

async function toggleOutreachDaemon() {
  if (currentOutreachStatus === 'daemon') {
    await stopOutreach();
    return;
  }
  const autoSend = document.getElementById('chk-outreach-auto-send').checked;
  if (autoSend && !confirmLiveAutoSend('The daemon')) return;
  const interval = parseInt(document.getElementById('input-outreach-interval').value || '60', 10);
  try {
    const res = await fetch('/api/outreach/daemon/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval_minutes: interval, auto_send: autoSend })
    });
    const data = await res.json();
    showToast(data.message || 'Outreach daemon started.', res.ok ? 'success' : 'error');
    fetchStatus();
  } catch (err) {
    showToast(`Error: ${err}`, 'error');
  }
}

async function stopOutreach() {
  try {
    const res = await fetch('/api/outreach/stop', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'Outreach stopped.', 'success');
    fetchStatus();
  } catch (err) {
    showToast(`Failed to stop outreach: ${err}`, 'error');
  }
}

function updateOutreachControls(outreach) {
  const status = outreach.status || 'idle';
  const wasBusy = currentOutreachStatus !== 'idle';
  currentOutreachStatus = status;

  document.getElementById('btn-outreach-run').disabled = status !== 'idle';
  document.getElementById('btn-outreach-daemon').disabled = status === 'running';
  document.getElementById('outreach-daemon-label').textContent =
    status === 'daemon' ? 'Stop Auto-Outreach Daemon' : 'Start Auto-Outreach Daemon';
  document.getElementById('btn-outreach-stop').style.display = status === 'running' ? 'inline-flex' : 'none';
  document.getElementById('outreach-step').textContent = outreach.current_step || 'Outreach Ready';
  if (outreach.stats) document.getElementById('tab-outreach-count').textContent = outreach.stats.total || 0;

  // Keep the contact table live while a cycle runs, and refresh once when it finishes
  const outreachTabOpen = document.getElementById('tab-outreach').classList.contains('active');
  if (outreachTabOpen && (status !== 'idle' || wasBusy)) loadContacts();
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------
function openPdfModal(pdfUrl, title) {
  const modal = document.getElementById('pdf-modal');
  const iframe = document.getElementById('pdf-iframe');
  const titleEl = document.getElementById('pdf-modal-title');

  titleEl.textContent = `Tailored Resume: ${title}`;
  iframe.src = pdfUrl;
  modal.classList.add('open');
}

function closePdfModal() {
  const modal = document.getElementById('pdf-modal');
  const iframe = document.getElementById('pdf-iframe');
  iframe.src = 'about:blank';
  modal.classList.remove('open');
}

function openScreenshotModal(imgUrl, title) {
  const modal = document.getElementById('screenshot-modal');
  const img = document.getElementById('screenshot-img');
  const titleEl = document.getElementById('screenshot-modal-title');

  titleEl.textContent = `Audit Verification: ${title}`;
  img.src = imgUrl;
  modal.classList.add('open');
}

function closeScreenshotModal() {
  const modal = document.getElementById('screenshot-modal');
  const img = document.getElementById('screenshot-img');
  img.src = '';
  modal.classList.remove('open');
}

// Close modals on clicking overlay background
window.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

// ---------------------------------------------------------------------------
// Toast Notification Utility
// ---------------------------------------------------------------------------
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
