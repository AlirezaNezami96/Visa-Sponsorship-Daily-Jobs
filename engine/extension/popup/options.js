'use strict';

const $ = (id) => document.getElementById(id);

async function loadSettings() {
  chrome.runtime.sendMessage({ action: 'GET_SETTINGS' }, (response) => {
    if (response && response.settings) {
      const { googleDocId, userName, apiBase } = response.settings;
      if (googleDocId) $('input-doc-id').value = googleDocId;
      if (userName) $('input-user-name').value = userName;
      if (apiBase) $('input-api-base').value = apiBase;
    }
  });
}

function showStatus(msg, type) {
  const el = $('settings-status');
  el.textContent = msg;
  el.className = `settings-status ${type}`;
}

async function saveSettings() {
  const googleDocId = $('input-doc-id').value.trim();
  const userName = $('input-user-name').value.trim();
  const apiBase = $('input-api-base').value.trim() || 'http://localhost:8000';

  if (!googleDocId) {
    showStatus('Please enter your Google Doc ID.', 'error');
    return;
  }
  if (!userName) {
    showStatus('Please enter your full name.', 'error');
    return;
  }

  chrome.runtime.sendMessage(
    {
      action: 'SAVE_SETTINGS',
      settings: { googleDocId, userName, apiBase },
    },
    (res) => {
      if (res && res.success) {
        showStatus('✅ Settings saved successfully!', 'success');
      } else {
        showStatus(res?.error || 'Failed to save settings.', 'error');
      }
    }
  );
}

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  $('btn-save-settings').addEventListener('click', saveSettings);
});
