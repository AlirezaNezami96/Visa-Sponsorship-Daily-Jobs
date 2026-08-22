/**
 * background.js — Service Worker
 *
 * Manages:
 *  1. Background async task lifecycle (tasks persist even if popup closes)
 *  2. Persistent memory & history caching per job URL
 *  3. Session lifecycle (init, auto-recovery on 401)
 *  4. API calls to the FastAPI backend
 *  5. Downloads of generated PDFs
 */

'use strict';

// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:8000';

async function getApiBase() {
  const result = await chrome.storage.sync.get(['apiBase']);
  return result.apiBase || API_BASE;
}

function normalizeUrl(rawUrl) {
  if (!rawUrl) return '';
  try {
    const u = new URL(rawUrl);
    const trackingParams = ['utm_source', 'utm_medium', 'utm_campaign', 'ref', 'source', 'trk', 'tracking', 'midToken', 'trkInfo'];
    trackingParams.forEach((p) => u.searchParams.delete(p));
    let path = u.pathname.replace(/\/+$/, '');
    return `${u.origin}${path}${u.search}`;
  } catch {
    return rawUrl.split('?')[0].replace(/\/+$/, '');
  }
}

// ── Session Management ────────────────────────────────────────────────────────

async function getOrCreateSession(googleDocId, forceNew = false) {
  if (!forceNew) {
    const stored = await chrome.storage.local.get(['sessionId', 'sessionExpiry', 'sessionDocId']);
    if (
      stored.sessionId &&
      stored.sessionExpiry > Date.now() &&
      stored.sessionDocId === googleDocId
    ) {
      return { sessionId: stored.sessionId, fromCache: true };
    }
  }

  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/session/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ google_doc_id: googleDocId }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Session init failed: ${response.status}`);
  }

  const data = await response.json();
  const sessionId = data.session_id;

  await chrome.storage.local.set({
    sessionId,
    sessionDocId: googleDocId,
    sessionExpiry: Date.now() + 90 * 60 * 1000,
  });

  return { sessionId, fromCache: false };
}

// ── API Call Helpers ──────────────────────────────────────────────────────────

async function callResumeApi(payload) {
  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/resume/tailor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const error = new Error(err.detail || `Resume API failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function callCoverLetterApi(payload) {
  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/cover-letter/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const error = new Error(err.detail || `Cover letter API failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function lookupJobMemoryApi(url) {
  try {
    const base = await getApiBase();
    const encoded = encodeURIComponent(url);
    const response = await fetch(`${base}/api/v1/jobs/lookup?url=${encoded}`);
    if (response.ok) {
      return await response.json();
    }
  } catch (e) {
    console.warn('Backend lookup failed:', e);
  }
  return { found: false };
}

// ── Download Helper ───────────────────────────────────────────────────────────

async function downloadDocument(downloadUrl, filename) {
  const base = await getApiBase();
  const fullUrl = downloadUrl.startsWith('http') ? downloadUrl : `${base}${downloadUrl}`;
  await chrome.downloads.download({ url: fullUrl, filename, saveAs: false });
}

// ── Task Management (Background Persistence) ──────────────────────────────────

async function setTaskState(url, taskObj) {
  const key = `task_${normalizeUrl(url)}`;
  await chrome.storage.local.set({ [key]: taskObj });
}

async function getTaskState(url) {
  const key = `task_${normalizeUrl(url)}`;
  const stored = await chrome.storage.local.get([key]);
  return stored[key] || null;
}

async function clearTaskState(url) {
  const key = `task_${normalizeUrl(url)}`;
  await chrome.storage.local.remove([key]);
}

// ── Message Router ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((err) => {
    sendResponse({ success: false, error: err.message });
  });
  return true; // Keep async channel open
});

async function handleMessage(message) {
  const { action } = message;

  if (action === 'GET_TASK_STATUS') {
    const { url } = message;
    const task = await getTaskState(url);
    return { success: true, task };
  }

  if (action === 'CHECK_JOB_MEMORY') {
    const { url } = message;
    // Check local task memory first
    const localTask = await getTaskState(url);
    if (localTask && localTask.status === 'COMPLETED') {
      return { success: true, found: true, source: 'local', data: localTask.result };
    }

    // Check backend SQLite database
    const dbResult = await lookupJobMemoryApi(url);
    if (dbResult && dbResult.found) {
      return { success: true, found: true, source: 'backend', data: dbResult.job };
    }

    return { success: true, found: false };
  }

  if (action === 'TAILOR_RESUME') {
    const { jobData, options } = message;
    const pageUrl = jobData.pageUrl;
    const settings = await chrome.storage.sync.get(['googleDocId', 'userName']);

    if (!settings.googleDocId) {
      throw new Error('No Google Doc ID configured. Please open the extension settings.');
    }

    // Set task to RUNNING in storage so popup can disconnect & reconnect safely
    await setTaskState(pageUrl, {
      status: 'RUNNING',
      type: 'resume',
      startedAt: Date.now(),
      companyName: jobData.companyName,
      jobTitle: jobData.jobTitle,
    });

    // Execute tailoring asynchronously
    (async () => {
      try {
        let { sessionId } = await getOrCreateSession(settings.googleDocId);
        let result;
        try {
          result = await callResumeApi({
            session_id: sessionId,
            job_description: jobData.jobDescription,
            job_url: pageUrl,
            company_name: jobData.companyName || 'Unknown Company',
            job_title: jobData.jobTitle || 'Unknown Role',
            options: options || {},
          });
        } catch (err) {
          if (err.status === 401 || err.message.includes('Session not found') || err.message.includes('expired')) {
            const reinit = await getOrCreateSession(settings.googleDocId, true);
            result = await callResumeApi({
              session_id: reinit.sessionId,
              job_description: jobData.jobDescription,
              job_url: pageUrl,
              company_name: jobData.companyName || 'Unknown Company',
              job_title: jobData.jobTitle || 'Unknown Role',
              options: options || {},
            });
          } else {
            throw err;
          }
        }

        await setTaskState(pageUrl, {
          status: 'COMPLETED',
          type: 'resume',
          result,
          companyName: jobData.companyName,
          jobTitle: jobData.jobTitle,
          completedAt: Date.now(),
        });
      } catch (err) {
        await setTaskState(pageUrl, {
          status: 'FAILED',
          type: 'resume',
          error: err.message,
          failedAt: Date.now(),
        });
      }
    })();

    return { success: true, status: 'RUNNING' };
  }

  if (action === 'GENERATE_COVER_LETTER') {
    const { jobData, options } = message;
    const pageUrl = jobData.pageUrl;
    const settings = await chrome.storage.sync.get(['googleDocId', 'userName']);
    const googleDocId = settings.googleDocId || '1a0qvUX6B2hqSdTT2EoKJF1e3L_m5ee4LxIZaMbU5FNA';
    const userName = settings.userName || 'Alireza Nezami';

    // Set task to RUNNING
    await setTaskState(pageUrl, {
      status: 'RUNNING',
      type: 'cover_letter',
      startedAt: Date.now(),
      companyName: jobData.companyName,
      jobTitle: jobData.jobTitle,
    });

    (async () => {
      try {
        let { sessionId } = await getOrCreateSession(googleDocId);
        let result;
        try {
          result = await callCoverLetterApi({
            session_id: sessionId,
            job_description: jobData.jobDescription,
            job_url: pageUrl,
            company_name: jobData.companyName || 'Unknown Company',
            job_title: jobData.jobTitle || 'Unknown Role',
            user_name: userName,
            tone: options?.tone || 'professional',
          });
        } catch (err) {
          if (err.status === 401 || err.message.includes('Session not found') || err.message.includes('expired')) {
            const reinit = await getOrCreateSession(googleDocId, true);
            result = await callCoverLetterApi({
              session_id: reinit.sessionId,
              job_description: jobData.jobDescription,
              job_url: pageUrl,
              company_name: jobData.companyName || 'Unknown Company',
              job_title: jobData.jobTitle || 'Unknown Role',
              user_name: userName,
              tone: options?.tone || 'professional',
            });
          } else {
            throw err;
          }
        }

        await setTaskState(pageUrl, {
          status: 'COMPLETED',
          type: 'cover_letter',
          result,
          companyName: jobData.companyName,
          jobTitle: jobData.jobTitle,
          completedAt: Date.now(),
        });
      } catch (err) {
        await setTaskState(pageUrl, {
          status: 'FAILED',
          type: 'cover_letter',
          error: err.message,
          failedAt: Date.now(),
        });
      }
    })();

    return { success: true, status: 'RUNNING' };
  }

  if (action === 'CLEAR_TASK_STATE') {
    const { url } = message;
    await clearTaskState(url);
    return { success: true };
  }

  if (action === 'DOWNLOAD_DOCUMENT') {
    const { downloadUrl, filename } = message;
    await downloadDocument(downloadUrl, filename);
    return { success: true };
  }

  if (action === 'GET_SETTINGS') {
    const settings = await chrome.storage.sync.get(['googleDocId', 'userName', 'apiBase']);
    return { success: true, settings };
  }

  if (action === 'SAVE_SETTINGS') {
    await chrome.storage.sync.set(message.settings);
    await chrome.storage.local.remove(['sessionId', 'sessionExpiry', 'sessionDocId']);
    return { success: true };
  }

  if (action === 'CONTENT_READY') {
    return { success: true };
  }

  return { success: false, error: `Unknown action: ${action}` };
}
