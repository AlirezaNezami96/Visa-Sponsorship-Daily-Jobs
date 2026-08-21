/**
 * popup.js — Extension Popup Controller
 *
 * Manages the popup UI state machine:
 *   no-jd → jd-found → loading → result
 *                            ↘ error
 *
 * Communicates with background.js (service worker) and content.js.
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────

let currentJobData = null;  // Extracted JD data from the current page
let currentResult = null;   // Last API response

// ── DOM Helpers ───────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const STATES = ['no-jd', 'jd-found', 'loading', 'result', 'error'];

function showState(name) {
  STATES.forEach((s) => {
    const el = $(`state-${s}`);
    if (el) el.classList.toggle('hidden', s !== name);
  });
}

function updateJobBanner(jobData) {
  if (!jobData) {
    $('job-banner').classList.add('hidden');
    return;
  }
  $('job-title-display').textContent = truncate(jobData.jobTitle || 'Unknown Role', 28);
  $('company-display').textContent   = truncate(jobData.companyName || 'Unknown Company', 22);
  $('jd-char-count').textContent     = `${jobData.charCount?.toLocaleString() || 0} chars`;
  $('job-banner').classList.remove('hidden');
}

function showError(message) {
  $('error-message').textContent = message || 'An unexpected error occurred.';
  showState('error');
}

function truncate(str, maxLen) {
  if (!str) return '';
  return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

function setProgress(pct) {
  $('progress-fill').style.width = `${pct}%`;
}

// ── Progress Animation ────────────────────────────────────────────────────────

let _progressTimer = null;

function startProgressAnimation() {
  let pct = 5;
  setProgress(pct);
  _progressTimer = setInterval(() => {
    // Logarithmic fill — never reaches 100% until manually completed
    if (pct < 85) {
      pct += (85 - pct) * 0.07;
      setProgress(pct);
    }
  }, 400);
}

function completeProgress() {
  clearInterval(_progressTimer);
  setProgress(100);
}

// ── Settings ──────────────────────────────────────────────────────────────────

async function loadSettings() {
  const { settings } = await sendToBackground({ action: 'GET_SETTINGS' });
  if (settings.googleDocId) $('input-doc-id').value = settings.googleDocId;
  if (settings.userName)    $('input-user-name').value = settings.userName;
  if (settings.apiBase)     $('input-api-base').value = settings.apiBase;
}

async function saveSettings() {
  const googleDocId = $('input-doc-id').value.trim();
  const userName    = $('input-user-name').value.trim();
  const apiBase     = $('input-api-base').value.trim() || 'http://localhost:8000';

  if (!googleDocId) {
    showSettingsStatus('Please enter your Google Doc ID.', 'error');
    return;
  }
  if (!userName) {
    showSettingsStatus('Please enter your name.', 'error');
    return;
  }

  const { success, error } = await sendToBackground({
    action: 'SAVE_SETTINGS',
    settings: { googleDocId, userName, apiBase },
  });

  if (success) {
    showSettingsStatus('✅ Settings saved!', 'success');
    setTimeout(() => closeSettings(), 1200);
  } else {
    showSettingsStatus(error || 'Failed to save settings.', 'error');
  }
}

function showSettingsStatus(msg, type) {
  const el = $('settings-status');
  el.textContent = msg;
  el.className = `settings-status ${type}`;
}

function openSettings() {
  loadSettings();
  $('settings-panel').classList.remove('hidden');
}

function closeSettings() {
  $('settings-panel').classList.add('hidden');
  $('settings-status').textContent = '';
}

// ── JD Extraction ─────────────────────────────────────────────────────────────

async function scanPage() {
  showState('loading');
  $('loading-title').textContent = 'Scanning page for job description...';
  $('loading-subtitle').textContent = 'Detecting job description elements on this page.';
  setProgress(30);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Inject content script if not already injected
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
      });
    } catch (_) { /* Already injected — ignore */ }

    await new Promise((r) => setTimeout(r, 300)); // Let content script initialize

    const response = await chrome.tabs.sendMessage(tab.id, { action: 'EXTRACT_JD' });
    setProgress(80);

    if (!response || !response.success) {
      showError(response?.error || 'Could not extract a job description from this page.');
      return;
    }

    currentJobData = response;
    setProgress(100);
    await new Promise((r) => setTimeout(r, 250));

    updateJobBanner(currentJobData);
    $('jd-preview').textContent = truncate(currentJobData.jobDescription, 300);
    showState('jd-found');
  } catch (err) {
    showError(`Scan failed: ${err.message}`);
  }
}

// ── Resume Tailoring ──────────────────────────────────────────────────────────

async function tailorResume() {
  if (!currentJobData) return;

  showState('loading');
  $('loading-title').textContent = 'Optimizing resume with Gemini 2.5 Pro...';
  $('loading-subtitle').textContent = 'Analyzing keywords, rewriting bullet points, and building your PDF.';
  startProgressAnimation();

  try {
    const { success, result, error } = await sendToBackground({
      action: 'TAILOR_RESUME',
      jobData: currentJobData,
      options: { ats_mode: true, max_bullet_additions: 3, preserve_dates: true },
    });

    completeProgress();
    await new Promise((r) => setTimeout(r, 300));

    if (!success) {
      showError(error || 'Resume tailoring failed.');
      return;
    }

    currentResult = result;
    displayResumeResult(result);
  } catch (err) {
    completeProgress();
    showError(err.message);
  }
}

function displayResumeResult(result) {
  $('result-title').textContent = '📄 Resume Optimized!';
  $('result-meta').textContent  =
    `${result.processing_time_ms ? `Processed in ${(result.processing_time_ms / 1000).toFixed(1)}s` : ''}`;

  // ATS Report
  const ats = result.ats_report;
  if (ats) {
    $('ats-section').classList.remove('hidden');
    const score = ats.ats_score_estimate || 0;
    $('ats-score-value').textContent = `${score}%`;
    $('ats-score-fill').style.width = `${score}%`;

    const kwContainer = $('ats-keywords');
    kwContainer.innerHTML = '';
    (ats.matched_keywords || []).slice(0, 6).forEach((kw) => {
      const tag = document.createElement('span');
      tag.className = 'kw-tag kw-matched';
      tag.textContent = kw;
      kwContainer.appendChild(tag);
    });
    (ats.missing_entirely || []).slice(0, 3).forEach((kw) => {
      const tag = document.createElement('span');
      tag.className = 'kw-tag kw-missing';
      tag.textContent = kw;
      kwContainer.appendChild(tag);
    });
  } else {
    $('ats-section').classList.add('hidden');
  }

  // Store download URL for the download button
  $('btn-download').dataset.url = result.download_url;
  $('btn-download').dataset.filename =
    `resume_${(currentJobData?.companyName || 'job').replace(/\s+/g, '_')}.pdf`;

  showState('result');
}

// ── Cover Letter ──────────────────────────────────────────────────────────────

async function generateCoverLetter() {
  if (!currentJobData) return;

  showState('loading');
  $('loading-title').textContent = 'Writing cover letter with Gemini 2.0 Flash...';
  $('loading-subtitle').textContent = 'Identifying pain points, matching your background, and crafting a human-toned letter.';
  startProgressAnimation();

  try {
    const { success, result, error } = await sendToBackground({
      action: 'GENERATE_COVER_LETTER',
      jobData: currentJobData,
    });

    completeProgress();
    await new Promise((r) => setTimeout(r, 300));

    if (!success) {
      showError(error || 'Cover letter generation failed.');
      return;
    }

    currentResult = result;
    $('result-title').textContent = '✉️ Cover Letter Ready!';
    $('ats-section').classList.add('hidden');
    $('result-meta').textContent  = result.processing_time_ms
      ? `Generated in ${(result.processing_time_ms / 1000).toFixed(1)}s`
      : '';
    $('btn-download').dataset.url = result.download_url;
    $('btn-download').dataset.filename =
      `cover_letter_${(currentJobData?.companyName || 'job').replace(/\s+/g, '_')}.pdf`;

    showState('result');
  } catch (err) {
    completeProgress();
    showError(err.message);
  }
}

// ── Download ──────────────────────────────────────────────────────────────────

async function downloadDocument(url, filename) {
  const { success, error } = await sendToBackground({
    action: 'DOWNLOAD_DOCUMENT',
    downloadUrl: url,
    filename: filename || 'document.pdf',
  });
  if (!success) showError(error || 'Download failed.');
}

// ── Background Messenger ──────────────────────────────────────────────────────

function sendToBackground(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response || {});
    });
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  showState('no-jd');

  // Wire up buttons
  $('btn-settings').addEventListener('click', openSettings);
  $('btn-close-settings').addEventListener('click', closeSettings);
  $('btn-save-settings').addEventListener('click', saveSettings);

  $('btn-scan').addEventListener('click', scanPage);
  $('btn-rescan').addEventListener('click', scanPage);
  $('btn-retry').addEventListener('click', () => showState(currentJobData ? 'jd-found' : 'no-jd'));
  $('btn-back').addEventListener('click', () => showState('jd-found'));

  $('btn-tailor-resume').addEventListener('click', tailorResume);
  $('btn-cover-letter').addEventListener('click', generateCoverLetter);

  $('btn-download').addEventListener('click', () => {
    const btn = $('btn-download');
    downloadDocument(btn.dataset.url, btn.dataset.filename);
  });

  // Auto-scan on popup open if we're on a job page
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const isJobPage = /jobs|careers|job-offer|posting|apply|positions/i.test(tab.url || '');
    if (isJobPage) {
      await scanPage();
    }
  } catch (_) { /* Not on a job page — show default state */ }
}

document.addEventListener('DOMContentLoaded', init);
