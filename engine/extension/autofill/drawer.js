/**
 * drawer.js — In-Page Slide-Out Right Panel & Field Progress Tracker with Hiring Contacts
 */

export class CopilotDrawer {
  constructor(atsName, onStartAutofill, getJobData) {
    this.atsName = atsName;
    this.onStartAutofill = onStartAutofill;
    this.getJobData = getJobData || (() => ({}));
    this.el = null;
    this.fieldRows = new Map();
    this.contactsCache = null;
    this.isContactsLoading = false;
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
        <button class="job-os-drawer-close" id="job-os-drawer-close-btn">&times;</button>
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

        <!-- ── Autofill Application Button ── -->
        <button class="job-os-btn-autofill" id="job-os-btn-autofill-drawer">
          <span>⚡</span>
          <span>Autofill Application</span>
        </button>

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

    document.getElementById('job-os-btn-autofill-drawer').addEventListener('click', () => {
      if (this.onStartAutofill) {
        document.getElementById('job-os-btn-autofill-drawer').disabled = true;
        this.setStatus('Autofilling fields sequentially...');
        this.onStartAutofill();
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
      console.debug('[HiringContacts] Discovery error:', err);
    }
  }

  setStatus(msg) {
    const banner = document.getElementById('job-os-status-banner');
    if (banner) banner.textContent = msg;
  }

  addFieldRow(fieldKey, labelText, targetElement) {
    const list = document.getElementById('job-os-field-list');
    if (!list || this.fieldRows.has(fieldKey)) return;

    const row = document.createElement('div');
    row.className = 'job-os-field-row';
    row.id = `row-${fieldKey}`;
    row.innerHTML = `
      <span style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px;">
        ${labelText || 'Field'}
      </span>
      <span class="row-status" style="color: #94a3b8;">Pending</span>
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

  showComplete(filledCount, skippedCount) {
    this.setStatus(`✅ Finished filling form. Please review every field before submitting.`);
    const btn = document.getElementById('job-os-btn-autofill-drawer');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Refill Form';
    }
    this.updateFooter(filledCount, skippedCount);
  }
}
