/**
 * popup.js — Extension Popup Controller
 *
 * Manages:
 *   1. Background task reconnection (resumes progress if popup was closed during generation)
 *   2. Persistent memory recognition (identifies previously tailored jobs by URL)
 *   3. UI State Machine: no-jd → jd-found → loading → result | error
 *   4. Communication with background.js & content.js
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────

let currentJobData = null;  // Extracted JD data from the current page
let currentResult = null;   // Active or saved API response
let activePollInterval = null;

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
  stopProgressTracking();
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

// ── Progress & Background Task Tracker ────────────────────────────────────────

let _progressTimer = null;

function startProgressAnimation(startTime = Date.now(), title = 'Optimizing documents with Gemini 3.7 Flash...') {
  $('loading-title').textContent = title;
  
  function updateElapsed() {
    const elapsedSec = Math.floor((Date.now() - startTime) / 1000);
    $('loading-subtitle').textContent = `Running in background... (${elapsedSec}s elapsed). You can safely close this popup.`;
  }
  updateElapsed();

  let pct = 10;
  setProgress(pct);
  
  clearInterval(_progressTimer);
  _progressTimer = setInterval(() => {
    updateElapsed();
    if (pct < 90) {
      pct += (90 - pct) * 0.05;
      setProgress(pct);
    }
  }, 1000);
}

function stopProgressTracking() {
  clearInterval(_progressTimer);
  clearInterval(activePollInterval);
  activePollInterval = null;
}

function completeProgress() {
  stopProgressTracking();
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
    if (!tab || !tab.id) throw new Error('No active tab found.');

    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
      });
    } catch (_) { /* Already injected or restricted page */ }

    await new Promise((r) => setTimeout(r, 250));

    let response = null;
    try {
      response = await chrome.tabs.sendMessage(tab.id, { action: 'EXTRACT_JD' });
    } catch (_) {
      // Retry once after 300ms
      await new Promise((r) => setTimeout(r, 300));
      try {
        response = await chrome.tabs.sendMessage(tab.id, { action: 'EXTRACT_JD' });
      } catch (retryErr) {
        console.warn('Direct message failed, attempting script fallback:', retryErr);
      }
    }

    setProgress(80);

    if (!response || !response.success) {
      showError(response?.error || 'Could not extract a job description from this page. Try scrolling or refreshing.');
      return;
    }

    currentJobData = response;
    setProgress(100);
    await new Promise((r) => setTimeout(r, 150));

    updateJobBanner(currentJobData);
    if ($('jd-preview')) {
      $('jd-preview').textContent = truncate(currentJobData.jobDescription, 260);
    }

    // Check persistent memory for this URL
    await checkJobMemory(currentJobData.pageUrl);

    showState('jd-found');

    // Automatically trigger hiring contacts discovery in background
    fetchPopupHiringContacts(false);
  } catch (err) {
    showError(`Scan failed: ${err.message}`);
  }
}

let popupContactsCache = null;

async function fetchPopupHiringContacts(forceRefresh = false) {
  if (!currentJobData) return;
  if (!forceRefresh && popupContactsCache) return;

  const btn = $('btn-find-contacts');
  const textSpan = $('btn-find-contacts-text');
  const card = $('popup-contacts-card');
  const list = $('popup-contacts-list');
  const countText = $('popup-contacts-count');

  if (!btn || !textSpan) return;

  textSpan.textContent = 'Finding Hiring Contacts...';
  btn.style.opacity = '0.85';

  try {
    const resp = await sendToBackground({
      action: 'FIND_HIRING_CONTACTS',
      payload: {
        company_name: currentJobData.companyName,
        job_title: currentJobData.jobTitle,
        page_url: currentJobData.pageUrl,
        jd_text: currentJobData.jobDescription,
        force_refresh: forceRefresh,
      },
    });

    btn.style.opacity = '1';

    if (resp && resp.success && Array.isArray(resp.contacts) && resp.contacts.length > 0) {
      popupContactsCache = resp;
      const count = resp.contacts.length;
      textSpan.textContent = `${count} Contact${count > 1 ? 's' : ''} Found`;
      btn.style.background = '#0a66c2';
      btn.style.color = '#ffffff';
      btn.style.borderColor = '#0a66c2';

      if (countText) {
        countText.textContent = `${count} relevant contact${count > 1 ? 's' : ''} found`;
      }

      if (list) {
        list.innerHTML = '';
        resp.contacts.forEach((c) => {
          const item = document.createElement('div');
          item.style.cssText = 'background: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 6px 8px; font-size: 11px;';
          item.innerHTML = `
            <div style="font-weight: 600; color: #f8fafc;">${c.name}</div>
            <div style="color: #94a3b8; font-size: 10px;">${c.title}</div>
          `;
          list.appendChild(item);
        });
      }

      if (card) card.classList.remove('hidden');
    } else if (resp && resp.success && resp.contacts && resp.contacts.length === 0) {
      textSpan.textContent = 'No hiring contacts found';
    } else {
      const errorMsg = resp?.error || 'Find Hiring Contacts';
      textSpan.textContent = errorMsg.includes('identify') ? 'Unable to identify company' : 'Find Hiring Contacts (Retry)';
    }
  } catch (err) {
    btn.style.opacity = '1';
    textSpan.textContent = 'Find Hiring Contacts (Retry)';
  }
}

async function checkJobMemory(pageUrl) {
  try {
    const res = await sendToBackground({ action: 'CHECK_JOB_MEMORY', url: pageUrl });
    const memoryBadge = $('memory-badge');
    if (res && res.found && res.data) {
      const data = res.data;
      memoryBadge.classList.remove('hidden');
      const score = data.ats_score || data.ats_report?.ats_score_estimate || 0;
      const dateStr = data.updated_at
        ? new Date(data.updated_at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        : 'Recently';

      $('memory-details').textContent = `Match Score: ${score}% · Saved on ${dateStr}`;
      $('btn-view-previous').onclick = () => {
        if (data.download_url || data.resume_doc_id) {
          displayResumeResult(data);
        } else if (data.cover_letter_doc_id) {
          displayCoverLetterResult(data);
        }
      };
    } else {
      memoryBadge.classList.add('hidden');
    }
  } catch (e) {
    console.warn('Memory check failed:', e);
  }
}

// ── Resume Tailoring (Background Persistent) ───────────────────────────────────

async function tailorResume() {
  if (!currentJobData) return;

  showState('loading');
  startProgressAnimation(Date.now(), 'Optimizing resume with Gemini 3.7 Flash...');

  try {
    // 1. Kick off background task (runs independently of popup)
    await sendToBackground({
      action: 'TAILOR_RESUME',
      jobData: currentJobData,
      options: { ats_mode: true, max_bullet_additions: 3, preserve_dates: true },
    });

    // 2. Poll background task status
    pollTaskStatus(currentJobData.pageUrl);
  } catch (err) {
    showError(err.message);
  }
}

function pollTaskStatus(url) {
  stopProgressTracking();
  
  const checkStatus = async () => {
    try {
      const res = await sendToBackground({ action: 'GET_TASK_STATUS', url });
      const task = res?.task;
      if (!task) return;

      if (task.status === 'RUNNING') {
        startProgressAnimation(task.startedAt || Date.now(), 
          task.type === 'cover_letter' ? 'Writing cover letter...' : 'Optimizing resume with Gemini 3.7 Flash...'
        );
      } else if (task.status === 'COMPLETED') {
        completeProgress();
        currentResult = task.result;
        if (task.type === 'cover_letter') {
          displayCoverLetterResult(task.result);
        } else {
          displayResumeResult(task.result);
        }
      } else if (task.status === 'FAILED') {
        showError(task.error || 'Generation failed.');
      }
    } catch (e) {
      console.warn('Task poll error:', e);
    }
  };

  checkStatus();
  activePollInterval = setInterval(checkStatus, 1500);
}

function displayResumeResult(result) {
  $('result-title').textContent = '📄 Resume Optimized!';
  $('result-meta').textContent =
    result.processing_time_ms ? `Processed in ${(result.processing_time_ms / 1000).toFixed(1)}s` : '';

  // ATS Report
  const ats = result.ats_report || {
    ats_score_estimate: result.ats_score || 0,
    matched_keywords: result.matched_keywords || [],
    missing_entirely: result.missing_keywords || [],
  };

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

  // Build download URL with naming params for a meaningful filename
  const companyName = currentJobData?.companyName || result.company_name || 'Company';
  const jobTitle = currentJobData?.jobTitle || result.job_title || 'Resume';
  const safeCompany = (companyName || 'Company').replace(/[^\w\-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'Company';
  const baseUrl = result.download_url || (result.resume_doc_id ? `/api/v1/document/saved/${result.resume_doc_id}` : '');
  const downloadUrl = baseUrl
    ? `${baseUrl}?company=${encodeURIComponent(companyName)}&job_title=${encodeURIComponent(jobTitle)}&doc_type=resume`
    : '';
  $('btn-download').dataset.url = downloadUrl;
  $('btn-download').dataset.filename = `Resume_Alireza_Nezami_Senior_Android_Developer_${safeCompany}.pdf`;

  // Google Doc link
  const btnGDoc = $('btn-open-gdoc');
  if (result.google_doc_url) {
    btnGDoc.href = result.google_doc_url;
    btnGDoc.classList.remove('hidden');
  } else {
    btnGDoc.classList.add('hidden');
  }

  showState('result');
}

// ── Cover Letter ──────────────────────────────────────────────────────────────

async function generateCoverLetter() {
  if (!currentJobData) return;

  showState('loading');
  startProgressAnimation(Date.now(), 'Writing cover letter with Gemini...');

  try {
    await sendToBackground({
      action: 'GENERATE_COVER_LETTER',
      jobData: currentJobData,
      options: { tone: 'professional' },
    });

    pollTaskStatus(currentJobData.pageUrl);
  } catch (err) {
    showError(err.message);
  }
}

function displayCoverLetterResult(result) {
  $('result-title').textContent = '✉️ Cover Letter Ready!';
  $('ats-section').classList.add('hidden');
  $('btn-open-gdoc').classList.add('hidden');
  $('result-meta').textContent = result.processing_time_ms
    ? `Generated in ${(result.processing_time_ms / 1000).toFixed(1)}s`
    : '';

  const companyName = currentJobData?.companyName || result.company_name || 'Company';
  const jobTitle = currentJobData?.jobTitle || result.job_title || 'Role';
  const safeCompany = (companyName || 'Company').replace(/[^\w\-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'Company';
  const baseUrl = result.download_url || (result.cover_letter_doc_id ? `/api/v1/document/saved/${result.cover_letter_doc_id}` : '');
  const downloadUrl = baseUrl
    ? `${baseUrl}?company=${encodeURIComponent(companyName)}&job_title=${encodeURIComponent(jobTitle)}&doc_type=cover_letter`
    : '';
  $('btn-download').dataset.url = downloadUrl;
  $('btn-download').dataset.filename = `CoverLetter_Alireza_Nezami_Senior_Android_Developer_${safeCompany}.pdf`;

  showState('result');
}

// ── Download ──────────────────────────────────────────────────────────────────

async function downloadDocument(url, filename) {
  if (!url) {
    showError('Download URL not found. Please re-optimize.');
    return;
  }
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

async function triggerAutofill() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) throw new Error('No active tab found.');

    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
      });
    } catch (_) { /* Injected */ }

    await chrome.tabs.sendMessage(tab.id, { action: 'TRIGGER_AUTOFILL' });
    window.close(); // Close popup so user sees the live on-page autofill
  } catch (err) {
    showError(`Could not start autofill: ${err.message}`);
  }
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

  if ($('btn-find-contacts')) {
    $('btn-find-contacts').addEventListener('click', () => {
      if (popupContactsCache && popupContactsCache.linkedin_search_url) {
        window.open(popupContactsCache.linkedin_search_url, '_blank');
      } else {
        fetchPopupHiringContacts(true);
      }
    });
  }

  if ($('btn-popup-linkedin-search')) {
    $('btn-popup-linkedin-search').addEventListener('click', () => {
      if (popupContactsCache && popupContactsCache.linkedin_search_url) {
        window.open(popupContactsCache.linkedin_search_url, '_blank');
      }
    });
  }

  if ($('btn-autofill-app')) $('btn-autofill-app').addEventListener('click', triggerAutofill);
  if ($('btn-autofill-direct')) $('btn-autofill-direct').addEventListener('click', triggerAutofill);

  $('btn-tailor-resume').addEventListener('click', tailorResume);
  $('btn-cover-letter').addEventListener('click', generateCoverLetter);

  $('btn-download').addEventListener('click', () => {
    const btn = $('btn-download');
    downloadDocument(btn.dataset.url, btn.dataset.filename);
  });

  // Check if active tab has a running or completed task
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url) {
      const { task } = await sendToBackground({ action: 'GET_TASK_STATUS', url: tab.url });
      
      if (task && task.status === 'RUNNING') {
        // Restore job data context so back button and UI work correctly after reconnect
        if (task.companyName || task.jobTitle) {
          currentJobData = {
            pageUrl: tab.url,
            companyName: task.companyName || 'Unknown Company',
            jobTitle: task.jobTitle || 'Unknown Role',
            jobDescription: '',
            charCount: 0,
          };
          updateJobBanner(currentJobData);
        }
        showState('loading');
        startProgressAnimation(task.startedAt || Date.now(),
          task.type === 'cover_letter' ? 'Writing cover letter...' : 'Optimizing resume with Gemini...'
        );
        pollTaskStatus(tab.url);
        return;
      }
      
      if (task && task.status === 'COMPLETED') {
        // Restore job data context from saved task state
        if (task.companyName || task.jobTitle) {
          currentJobData = {
            pageUrl: tab.url,
            companyName: task.companyName || 'Unknown Company',
            jobTitle: task.jobTitle || 'Unknown Role',
            jobDescription: '',
            charCount: 0,
          };
          updateJobBanner(currentJobData);
        }
        if (task.type === 'cover_letter') {
          displayCoverLetterResult(task.result);
        } else {
          displayResumeResult(task.result);
        }
        return;
      }

      // Check if it's a job page to auto-scan
      const isJobPage = /jobs|careers|job-offer|posting|apply|positions/i.test(tab.url || '');
      if (isJobPage) {
        await scanPage();
      }
    }
  } catch (_) { /* Default state */ }
}

document.addEventListener('DOMContentLoaded', init);
