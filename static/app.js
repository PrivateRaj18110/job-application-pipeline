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
