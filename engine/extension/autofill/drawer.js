/**
 * drawer.js — Universal Copilot Drawer with Confidence Badges, Stop Control & Inspector
 */

import { globalFieldInspector } from './inspector.js';
import { ApplicationSession } from './session.js';

export class CopilotDrawer {
  constructor(atsName, onStartAutofill, getJobData) {
    this.atsName = atsName;
    this.onStartAutofill = onStartAutofill;
    this.getJobData = getJobData || (() => ({}));
    this.el = null;
    this.fieldRows = new Map();
    this.contactsCache = null;
    this.isContactsLoading = false;
    this.session = new ApplicationSession({});
    this.isInspecting = false;
  }

  mount() {
    if (document.getElementById('job-os-copilot-drawer')) return;

    this.el = document.createElement('div');
    this.el.id = 'job-os-copilot-drawer';
    this.el.innerHTML = `
      <div class="job-os-drawer-header">
        <div class="job-os-drawer-title">
          <span>🚀 Job OS Copilot</span>
          <span class="job-os-drawer-badge">${this.atsName}</span>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          <button class="job-os-drawer-tool-btn" id="job-os-btn-inspect" title="Toggle Developer Field Inspector">🔍</button>
          <button class="job-os-drawer-close" id="job-os-drawer-close-btn">&times;</button>
        </div>
      </div>

      <div class="job-os-drawer-body">
        <!-- ── Hiring Contacts Button (Immediately ABOVE Autofill) ── -->
        <button class="job-os-btn-contacts" id="job-os-btn-contacts-drawer">
          <span class="btn-icon-inline">👥</span>
          <span id="job-os-btn-contacts-text">Find Hiring Contacts</span>
        </button>

        <div id="job-os-contacts-card" class="job-os-contacts-card hidden">
          <div class="job-os-contacts-header">
            <span id="job-os-contacts-count-text">Hiring Contacts</span>
          </div>
          <div class="job-os-contacts-list" id="job-os-contacts-list"></div>
          <button class="job-os-btn-linkedin-search" id="job-os-btn-linkedin-search">
            <span>💼</span>
            <span>Find on LinkedIn</span>
          </button>
        </div>

        <!-- ── Action Controls ── -->
        <div style="display: flex; gap: 8px;">
          <button class="job-os-btn-autofill" id="job-os-btn-autofill-drawer" style="flex: 1;">
            <span>⚡</span>
            <span>Autofill Application</span>
          </button>
          <button class="job-os-btn-stop hidden" id="job-os-btn-stop" style="background: #ef4444; color: #fff; border: none; border-radius: 8px; padding: 0 12px; font-weight: 700; cursor: pointer;">
            <span>⏹️ Stop</span>
          </button>
        </div>

        <div id="job-os-status-banner" style="font-size: 12px; color: #94a3b8; padding: 4px 0;">
          Ready to sequentially autofill with tailored resume.
        </div>

        <div class="job-os-field-list" id="job-os-field-list"></div>
      </div>

      <div class="job-os-drawer-footer">
        <span id="job-os-footer-stats">0 filled · 0 skipped</span>
        <span style="font-weight: 600; color: #cbd5e1;">Review & Submit Yourself</span>
      </div>
    `;

    document.body.appendChild(this.el);

    document.getElementById('job-os-drawer-close-btn').addEventListener('click', () => {
      this.close();
    });

    document.getElementById('job-os-btn-inspect').addEventListener('click', () => {
      this.isInspecting = !this.isInspecting;
      if (this.isInspecting) {
        globalFieldInspector.enable();
        document.getElementById('job-os-btn-inspect').style.background = '#3b82f6';
      } else {
        globalFieldInspector.disable();
        document.getElementById('job-os-btn-inspect').style.background = 'transparent';
      }
    });

    const stopBtn = document.getElementById('job-os-btn-stop');
    stopBtn.addEventListener('click', () => {
      this.session.stop();
      this.setStatus('⏹️ Stopping autofill...');
    });

    document.getElementById('job-os-btn-autofill-drawer').addEventListener('click', () => {
      if (this.onStartAutofill) {
        this.session.startFilling();
        document.getElementById('job-os-btn-autofill-drawer').disabled = true;
        stopBtn.classList.remove('hidden');
        this.setStatus('Autofilling fields sequentially...');
        this.onStartAutofill(this.session);
      }
    });

    const contactsBtn = document.getElementById('job-os-btn-contacts-drawer');
    contactsBtn.addEventListener('click', () => {
      if (this.contactsCache && this.contactsCache.linkedin_search_url) {
        window.open(this.contactsCache.linkedin_search_url, '_blank');
      } else {
        this.fetchHiringContacts(true);
      }
    });

    const searchBtn = document.getElementById('job-os-btn-linkedin-search');
    searchBtn.addEventListener('click', () => {
      if (this.contactsCache && this.contactsCache.linkedin_search_url) {
        window.open(this.contactsCache.linkedin_search_url, '_blank');
      }
    });

    // Automatically trigger hiring contacts discovery in the background
    this.fetchHiringContacts(false);
  }

  open() {
    if (this.el) {
      this.el.classList.add('open');
      this.fetchHiringContacts(false);
    }
  }

  close() {
    if (this.el) this.el.classList.remove('open');
  }

  toggle() {
    if (this.el) {
      this.el.classList.toggle('open');
      if (this.el.classList.contains('open')) {
        this.fetchHiringContacts(false);
      }
    }
  }

  async fetchHiringContacts(forceRefresh = false) {
    if (this.isContactsLoading) return;
    if (!forceRefresh && this.contactsCache) return;

    const btn = document.getElementById('job-os-btn-contacts-drawer');
    const textSpan = document.getElementById('job-os-btn-contacts-text');
    const card = document.getElementById('job-os-contacts-card');
    const list = document.getElementById('job-os-contacts-list');
    const countText = document.getElementById('job-os-contacts-count-text');

    if (!btn || !textSpan) return;

    this.isContactsLoading = true;
    btn.classList.add('loading');
    textSpan.textContent = 'Finding Hiring Contacts...';

    const jobData = this.getJobData();

    try {
      const resp = await chrome.runtime.sendMessage({
        action: 'FIND_HIRING_CONTACTS',
        payload: {
          company_name: jobData.companyName || '',
          job_title: jobData.jobTitle || '',
          page_url: jobData.pageUrl || window.location.href,
          jd_text: jobData.jobDescription || '',
          force_refresh: forceRefresh,
        },
      });

      this.isContactsLoading = false;
      btn.classList.remove('loading');

      if (resp && resp.success && Array.isArray(resp.contacts) && resp.contacts.length > 0) {
        this.contactsCache = resp;
        const count = resp.contacts.length;
        btn.classList.add('success');
        textSpan.textContent = `${count} Contact${count > 1 ? 's' : ''} Found`;

        if (countText) {
          countText.textContent = `${count} relevant contact${count > 1 ? 's' : ''} found`;
        }

        if (list) {
          list.innerHTML = '';
          resp.contacts.forEach((c) => {
            const item = document.createElement('div');
            item.className = 'job-os-contact-item';
            item.innerHTML = `
              <div class="job-os-contact-name">${c.name}</div>
              <div class="job-os-contact-title">${c.title}</div>
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
      this.isContactsLoading = false;
      if (btn) btn.classList.remove('loading');
      if (textSpan) textSpan.textContent = 'Find Hiring Contacts (Retry)';
    }
  }

  setStatus(msg) {
    const banner = document.getElementById('job-os-status-banner');
    if (banner) banner.textContent = msg;
  }

  clearFieldRows() {
    const list = document.getElementById('job-os-field-list');
    if (list) list.innerHTML = '';
    this.fieldRows.clear();
  }

  addFieldRow(fieldKey, labelText, targetElement, confidenceTier = 'SAFE_AUTOFILL') {
    const list = document.getElementById('job-os-field-list');
    if (!list || this.fieldRows.has(fieldKey)) return;

    let badgeColor = '#10b981';
    let badgeText = 'Safe';
    if (confidenceTier === 'PROBABLE_AUTOFILL') {
      badgeColor = '#60a5fa';
      badgeText = 'Probable';
    } else if (confidenceTier === 'AI_REVIEW') {
      badgeColor = '#a855f7';
      badgeText = 'AI Review';
    } else if (confidenceTier === 'UNKNOWN') {
      badgeColor = '#94a3b8';
      badgeText = 'Unknown';
    }

    const row = document.createElement('div');
    row.className = 'job-os-field-row';
    row.id = `row-${fieldKey}`;
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
        <span style="font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,0.08); color: ${badgeColor};">
          ${badgeText}
        </span>
        <span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px;">
          ${labelText || 'Field'}
        </span>
      </div>
      <span class="row-status" style="color: #94a3b8; font-size: 11px;">Pending</span>
    `;

    row.addEventListener('click', () => {
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetElement.classList.add('job-os-highlight-field');
        setTimeout(() => targetElement.classList.remove('job-os-highlight-field'), 1500);
      }
    });

    list.appendChild(row);
    this.fieldRows.set(fieldKey, row);
  }

  updateFieldRow(fieldKey, status, detailText) {
    const row = this.fieldRows.get(fieldKey);
    if (!row) return;

    row.classList.remove('active', 'success', 'skipped');
    const statusSpan = row.querySelector('.row-status');

    if (status === 'active') {
      row.classList.add('active');
      if (statusSpan) {
        statusSpan.style.color = '#60a5fa';
        statusSpan.textContent = '⏳ Filling…';
      }
    } else if (status === 'success') {
      row.classList.add('success');
      if (statusSpan) {
        statusSpan.style.color = '#10b981';
        statusSpan.textContent = detailText ? `✅ ${detailText}` : '✅ Filled';
      }
    } else if (status === 'skipped') {
      row.classList.add('skipped');
      if (statusSpan) {
        statusSpan.style.color = '#fbbf24';
        statusSpan.textContent = detailText ? `⚠️ ${detailText}` : '⚠️ Skipped';
      }
    }
  }

  updateFooter(filledCount, skippedCount) {
    const stats = document.getElementById('job-os-footer-stats');
    if (stats) {
      stats.textContent = `${filledCount} filled · ${skippedCount} skipped`;
    }
  }

  showComplete(filledCount, skippedCount, aiCount = 0) {
    this.setStatus(`✅ Autofill finished. Review ${filledCount} filled fields before submitting manually.`);
    const btn = document.getElementById('job-os-btn-autofill-drawer');
    const stopBtn = document.getElementById('job-os-btn-stop');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Refill Form';
    }
    if (stopBtn) {
      stopBtn.classList.add('hidden');
    }
    this.updateFooter(filledCount, skippedCount);
  }
}
