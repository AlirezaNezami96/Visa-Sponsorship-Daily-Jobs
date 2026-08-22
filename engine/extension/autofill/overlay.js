/**
 * overlay.js — Floating Application Copilot UI
 */

export class AutofillOverlay {
  constructor(atsName, onStartAutofill) {
    this.atsName = atsName;
    this.onStartAutofill = onStartAutofill;
    this.el = null;
  }

  mount() {
    if (document.getElementById('job-os-copilot-overlay')) return;

    this.el = document.createElement('div');
    this.el.id = 'job-os-copilot-overlay';
    this.el.innerHTML = `
      <div class="job-os-header">
        <span style="font-weight: 700;">🚀 Job OS Copilot</span>
        <span class="job-os-badge" id="job-os-ats-badge">${this.atsName}</span>
      </div>
      <div class="job-os-body">
        <div id="job-os-status-text" style="font-weight: 500; color: #94a3b8;">Ready to autofill application</div>
        <div class="job-os-progress">
          <div class="job-os-progress-fill" id="job-os-progress-bar"></div>
        </div>
        <button class="job-os-btn-primary" id="job-os-btn-autofill">
          <span>⚡</span>
          <span>Autofill Application</span>
        </button>
        <div id="job-os-skipped-container" class="job-os-skipped-list" style="display: none;"></div>
      </div>
    `;

    document.body.appendChild(this.el);

    document.getElementById('job-os-btn-autofill').addEventListener('click', () => {
      if (this.onStartAutofill) {
        document.getElementById('job-os-btn-autofill').disabled = true;
        document.getElementById('job-os-status-text').textContent = 'Autofilling fields...';
        this.onStartAutofill();
      }
    });
  }

  updateProgress(current, total, fieldName) {
    const percent = Math.min(100, Math.round((current / (total || 1)) * 100));
    const bar = document.getElementById('job-os-progress-bar');
    const text = document.getElementById('job-os-status-text');
    if (bar) bar.style.width = `${percent}%`;
    if (text) text.textContent = `Filling: ${fieldName || 'field'} (${current}/${total})`;
  }

  showComplete(filledCount, skippedList = []) {
    const text = document.getElementById('job-os-status-text');
    const btn = document.getElementById('job-os-btn-autofill');
    const skippedCont = document.getElementById('job-os-skipped-container');

    if (text) text.textContent = `✅ Filled ${filledCount} fields. Review before submitting.`;
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Refill Form';
    }

    if (skippedList.length > 0 && skippedCont) {
      skippedCont.style.display = 'block';
      skippedCont.innerHTML = `<strong>⚠️ Check these ${skippedList.length} fields:</strong><br>${skippedList.join(', ')}`;
    }
  }
}
