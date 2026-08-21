/**
 * background.js — Service Worker
 *
 * Manages:
 *  1. Session lifecycle (init, persist session_id in chrome.storage.local)
 *  2. API calls to the FastAPI backend (keeps Gemini key server-side)
 *  3. Downloads of generated PDFs
 *
 * Manifest V3 Service Worker — no persistent state between events.
 */

'use strict';

// ── Config ─────────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:8000'; // Updated via options page in production

async function getApiBase() {
  const result = await chrome.storage.sync.get(['apiBase']);
  return result.apiBase || API_BASE;
}

// ── Session Management ────────────────────────────────────────────────────────

async function getOrCreateSession(googleDocId) {
  const stored = await chrome.storage.local.get(['sessionId', 'sessionExpiry', 'sessionDocId']);

  // Return cached session if still valid and same Google Doc
  if (
    stored.sessionId &&
    stored.sessionExpiry > Date.now() &&
    stored.sessionDocId === googleDocId
  ) {
    return { sessionId: stored.sessionId, fromCache: true };
  }

  // Create new session
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

  // Cache session for 90 minutes (TTL is 2h server-side)
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
    throw new Error(err.detail || `Resume API failed: ${response.status}`);
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
    throw new Error(err.detail || `Cover letter API failed: ${response.status}`);
  }
  return response.json();
}

// ── Download Helper ───────────────────────────────────────────────────────────

async function downloadDocument(downloadUrl, filename) {
  const base = await getApiBase();
  const fullUrl = downloadUrl.startsWith('http') ? downloadUrl : `${base}${downloadUrl}`;
  await chrome.downloads.download({ url: fullUrl, filename, saveAs: false });
}

// ── Message Router ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((err) => {
    sendResponse({ success: false, error: err.message });
  });
  return true; // Required to keep async channel open
});

async function handleMessage(message) {
  const { action } = message;

  if (action === 'TAILOR_RESUME') {
    const { jobData, options } = message;
    const settings = await chrome.storage.sync.get(['googleDocId', 'userName']);

    if (!settings.googleDocId) {
      throw new Error('No Google Doc ID configured. Please open the extension settings.');
    }

    const { sessionId } = await getOrCreateSession(settings.googleDocId);

    const result = await callResumeApi({
      session_id: sessionId,
      job_description: jobData.jobDescription,
      job_url: jobData.pageUrl,
      company_name: jobData.companyName || 'Unknown Company',
      job_title: jobData.jobTitle || 'Unknown Role',
      options: options || {},
    });

    // Store download URL for quick access
    await chrome.storage.local.set({ lastResumeResult: result });
    return { success: true, result };
  }

  if (action === 'GENERATE_COVER_LETTER') {
    const { jobData } = message;
    const settings = await chrome.storage.sync.get(['googleDocId', 'userName']);

    if (!settings.googleDocId) {
      throw new Error('No Google Doc ID configured. Please open the extension settings.');
    }
    if (!settings.userName) {
      throw new Error('Please set your name in the extension settings.');
    }

    const { sessionId } = await getOrCreateSession(settings.googleDocId);

    const result = await callCoverLetterApi({
      session_id: sessionId,
      job_description: jobData.jobDescription,
      job_url: jobData.pageUrl,
      company_name: jobData.companyName || 'Unknown Company',
      job_title: jobData.jobTitle || 'Unknown Role',
      user_name: settings.userName,
      tone: 'professional',
    });

    await chrome.storage.local.set({ lastCoverLetterResult: result });
    return { success: true, result };
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
    // Invalidate session when Google Doc ID changes
    await chrome.storage.local.remove(['sessionId', 'sessionExpiry', 'sessionDocId']);
    return { success: true };
  }

  if (action === 'CONTENT_READY') {
    return { success: true };
  }

  return { success: false, error: `Unknown action: ${action}` };
}
