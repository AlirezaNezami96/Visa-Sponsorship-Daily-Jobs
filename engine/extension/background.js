/**
 * background.js — Service Worker & Secure API Gateway
 *
 * All external network / HTTP API requests MUST pass through this worker.
 * Content scripts communicate solely via chrome.runtime.sendMessage.
 */

'use strict';

const API_BASE = 'http://localhost:8000';

async function getApiBase() {
  const result = await chrome.storage.sync.get(['apiBase']);
  return result.apiBase || API_BASE;
}

function arrayBufferToBase64(buffer) {
  let binary = '';
  const bytes = new Uint8Array(buffer);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
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

// ── API Gateway Calls ─────────────────────────────────────────────────────────

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

async function getApplicantProfile() {
  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/profile`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch profile: ${response.status}`);
  }
  return response.json();
}

async function batchAnswerQuestionsApi(payload) {
  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/autofill/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Batch answer failed: ${response.status}`);
  }
  return response.json();
}

async function findHiringContactsApi(payload) {
  const base = await getApiBase();
  const response = await fetch(`${base}/api/v1/contacts/find`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Hiring contacts search failed: ${response.status}`);
  }
  return response.json();
}

async function tailorResumeDirect(jobData, options = {}) {
  const settings = await chrome.storage.sync.get(['googleDocId']);
  const googleDocId = settings.googleDocId || '1a0qvUX6B2hqSdTT2EoKJF1e3L_m5ee4LxIZaMbU5FNA';
  let { sessionId } = await getOrCreateSession(googleDocId);

  let result;
  try {
    result = await callResumeApi({
      session_id: sessionId,
      job_description: jobData.jobDescription || 'Software Engineer',
      job_url: jobData.pageUrl,
      company_name: jobData.companyName || 'Company',
      job_title: jobData.jobTitle || 'Software Engineer',
      options,
    });
  } catch (err) {
    if (err.status === 401 || err.message.includes('Session not found') || err.message.includes('expired')) {
      const reinit = await getOrCreateSession(googleDocId, true);
      result = await callResumeApi({
        session_id: reinit.sessionId,
        job_description: jobData.jobDescription || 'Software Engineer',
        job_url: jobData.pageUrl,
        company_name: jobData.companyName || 'Company',
        job_title: jobData.jobTitle || 'Software Engineer',
        options,
      });
    } else {
      throw err;
    }
  }

  const base = await getApiBase();
  let pdfBase64 = null;
  const downloadUrl = result.download_url ? `${base}${result.download_url}` : `${base}/api/v1/document/saved/${result.resume_doc_id}`;
  try {
    const pdfRes = await fetch(downloadUrl);
    if (pdfRes.ok) {
      const arrayBuf = await pdfRes.arrayBuffer();
      pdfBase64 = arrayBufferToBase64(arrayBuf);
    }
  } catch (e) {
    console.warn('Could not fetch PDF bytes:', e);
  }

  const safeCompany = (jobData.companyName || 'Company').replace(/[^\w\-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'Company';
  const filename = `Resume_Alireza_Nezami_Senior_Android_Developer_${safeCompany}.pdf`;

  return {
    success: true,
    result,
    pdfBase64,
    filename,
    ats_report: result.ats_report,
  };
}

async function generateCoverLetterDirect(jobData, options = {}) {
  const settings = await chrome.storage.sync.get(['googleDocId', 'userName']);
  const googleDocId = settings.googleDocId || '1a0qvUX6B2hqSdTT2EoKJF1e3L_m5ee4LxIZaMbU5FNA';
  const userName = settings.userName || 'Alireza Nezami';
  let { sessionId } = await getOrCreateSession(googleDocId);

  let result;
  try {
    result = await callCoverLetterApi({
      session_id: sessionId,
      job_description: jobData.jobDescription || 'Software Engineer',
      job_url: jobData.pageUrl,
      company_name: jobData.companyName || 'Company',
      job_title: jobData.jobTitle || 'Software Engineer',
      user_name: userName,
      tone: options?.tone || 'professional',
    });
  } catch (err) {
    if (err.status === 401 || err.message.includes('Session not found') || err.message.includes('expired')) {
      const reinit = await getOrCreateSession(googleDocId, true);
      result = await callCoverLetterApi({
        session_id: reinit.sessionId,
        job_description: jobData.jobDescription || 'Software Engineer',
        job_url: jobData.pageUrl,
        company_name: jobData.companyName || 'Company',
        job_title: jobData.jobTitle || 'Software Engineer',
        user_name: userName,
        tone: options?.tone || 'professional',
      });
    } else {
      throw err;
    }
  }

  const base = await getApiBase();
  let pdfBase64 = null;
  const downloadUrl = result.download_url ? `${base}${result.download_url}` : `${base}/api/v1/document/saved/${result.cover_letter_doc_id}`;
  try {
    const pdfRes = await fetch(downloadUrl);
    if (pdfRes.ok) {
      const arrayBuf = await pdfRes.arrayBuffer();
      pdfBase64 = arrayBufferToBase64(arrayBuf);
    }
  } catch (e) {
    console.warn('Could not fetch cover letter PDF bytes:', e);
  }

  const safeCompany = (jobData.companyName || 'Company').replace(/[^\w\-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') || 'Company';
  const filename = `CoverLetter_Alireza_Nezami_Senior_Android_Developer_${safeCompany}.pdf`;

  return {
    success: true,
    result,
    cover_letter_text: result.cover_letter_text || '',
    pdfBase64,
    filename,
  };
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

// ── State Persistence ─────────────────────────────────────────────────────────

async function getTaskState(url) {
  const norm = normalizeUrl(url);
  const key = `task_${norm}`;
  const data = await chrome.storage.local.get([key]);
  return data[key] || null;
}

async function setTaskState(url, state) {
  const norm = normalizeUrl(url);
  const key = `task_${norm}`;
  await chrome.storage.local.set({ [key]: state });
}

async function clearTaskState(url) {
  const norm = normalizeUrl(url);
  const key = `task_${norm}`;
  await chrome.storage.local.remove([key]);
}

// ── Document Downloader ───────────────────────────────────────────────────────

async function downloadDocument(downloadUrl, filename) {
  const base = await getApiBase();
  const absoluteUrl = downloadUrl.startsWith('http') ? downloadUrl : `${base}${downloadUrl}`;
  return new Promise((resolve, reject) => {
    chrome.downloads.download(
      {
        url: absoluteUrl,
        filename: filename || 'resume.pdf',
        saveAs: false,
      },
      (downloadId) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else {
          resolve(downloadId);
        }
      }
    );
  });
}

// ── Message Dispatcher ────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then((res) => sendResponse(res))
    .catch((err) => sendResponse({ success: false, error: err.message }));
  return true; // Keep channel open for async response
});

async function handleMessage(message, sender) {
  const { action } = message;

  if (action === 'GET_PROFILE') {
    const profile = await getApplicantProfile();
    return { success: true, profile };
  }

  if (action === 'TAILOR_RESUME_DIRECT') {
    const res = await tailorResumeDirect(message.jobData, message.options);
    return res;
  }

  if (action === 'GENERATE_COVER_DIRECT') {
    const res = await generateCoverLetterDirect(message.jobData, message.options);
    return res;
  }

  if (action === 'BATCH_ANSWER') {
    const res = await batchAnswerQuestionsApi(message.payload);
    return res;
  }

  if (action === 'FIND_HIRING_CONTACTS') {
    const res = await findHiringContactsApi(message.payload);
    return res;
  }

  if (action === 'GET_AUTOFILL_CONFIG') {
    try {
      const base = await getApiBase();
      const resp = await fetch(`${base}/api/v1/autofill/config`);
      if (resp.ok) {
        return resp.json();
      }
    } catch (_) {}
    return { success: false };
  }

  if (action === 'CHECK_JOB_MEMORY') {
    const { url } = message;
    const norm = normalizeUrl(url);
    const task = await getTaskState(norm);
    if (task && task.status === 'COMPLETED') {
      return { found: true, data: task.result };
    }
    const backendData = await lookupJobMemoryApi(norm);
    if (backendData && backendData.found) {
      return { found: true, data: backendData.data };
    }
    return { found: false };
  }

  if (action === 'GET_TASK_STATUS') {
    const { url } = message;
    const task = await getTaskState(url);
    return { success: true, task };
  }

  if (action === 'START_TAILOR_TASK') {
    const { jobData, options } = message;
    const pageUrl = jobData.pageUrl;
    const settings = await chrome.storage.sync.get(['googleDocId']);

    if (!settings.googleDocId) {
      settings.googleDocId = '1a0qvUX6B2hqSdTT2EoKJF1e3L_m5ee4LxIZaMbU5FNA';
    }

    await setTaskState(pageUrl, {
      status: 'RUNNING',
      type: 'resume',
      startedAt: Date.now(),
      companyName: jobData.companyName,
      jobTitle: jobData.jobTitle,
    });

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
