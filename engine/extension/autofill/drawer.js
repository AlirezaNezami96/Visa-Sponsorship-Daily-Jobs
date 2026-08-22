/**
 * drawer.js — In-Page Slide-Out Right Panel & Field Progress Tracker
 */

export class CopilotDrawer {
  constructor(atsName, onStartAutofill) {
    this.atsName = atsName;
    this.onStartAutofill = onStartAutofill;
    this.el = null;
    this.fieldRows = new Map();
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
  }

  open() {
    if (this.el) this.el.classList.add('open');
  }

  close() {
    if (this.el) this.el.classList.remove('open');
  }

  toggle() {
    if (this.el) this.el.classList.toggle('open');
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
