/**
 * handle.js — Slim Draggable Right-Edge Tab Handle
 */

export class CopilotHandle {
  constructor(onToggleDrawer) {
    this.onToggleDrawer = onToggleDrawer;
    this.el = null;
    this.isDragging = false;
    this.startY = 0;
    this.startTop = 120;
  }

  async mount() {
    if (document.getElementById('job-os-copilot-handle')) return;

    this.el = document.createElement('div');
    this.el.id = 'job-os-copilot-handle';
    this.el.innerHTML = `
      <span class="job-os-handle-icon">⚡</span>
      <span class="job-os-handle-text">Job OS</span>
    `;

    // Restore saved top position
    try {
      const saved = await chrome.storage.local.get(['handleTop']);
      if (saved.handleTop) {
        this.el.style.top = `${saved.handleTop}px`;
      }
    } catch (_) {}

    document.body.appendChild(this.el);
    this._attachListeners();
  }

  _attachListeners() {
    let moved = false;

    this.el.addEventListener('mousedown', (e) => {
      this.isDragging = true;
      moved = false;
      this.startY = e.clientY;
      this.startTop = this.el.offsetTop;
      e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isDragging) return;
      const dy = e.clientY - this.startY;
      if (Math.abs(dy) > 3) moved = true;

      let newTop = this.startTop + dy;
      newTop = Math.max(20, Math.min(window.innerHeight - 130, newTop));
      this.el.style.top = `${newTop}px`;
    });

    window.addEventListener('mouseup', () => {
      if (this.isDragging) {
        this.isDragging = false;
        try {
          chrome.storage.local.set({ handleTop: this.el.offsetTop });
        } catch (_) {}
      }
    });

    this.el.addEventListener('click', () => {
      if (!moved && this.onToggleDrawer) {
        this.onToggleDrawer();
      }
    });
  }
}
