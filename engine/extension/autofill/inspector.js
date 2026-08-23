/**
 * inspector.js — Developer Field Inspector Mode
 */

import { extractSemanticLabel } from './labels.js';
import { classifyFormField } from './classifier.js';

export class FieldInspector {
  constructor() {
    this.overlayEl = null;
    this.isActive = false;
    this.hoverHandler = this.onHover.bind(this);
  }

  enable() {
    if (this.isActive) return;
    this.isActive = true;
    document.addEventListener('mouseover', this.hoverHandler, true);
    this.createOverlay();
  }

  disable() {
    if (!this.isActive) return;
    this.isActive = false;
    document.removeEventListener('mouseover', this.hoverHandler, true);
    if (this.overlayEl) {
      this.overlayEl.remove();
      this.overlayEl = null;
    }
  }

  createOverlay() {
    if (document.getElementById('job-os-inspector-card')) return;
    this.overlayEl = document.createElement('div');
    this.overlayEl.id = 'job-os-inspector-card';
    this.overlayEl.style.cssText = `
      position: fixed;
      bottom: 20px;
      left: 20px;
      z-index: 2147483647;
      background: #0f172a;
      color: #f8fafc;
      border: 1px solid #3b82f6;
      border-radius: 8px;
      padding: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 11px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      max-width: 320px;
      pointer-events: none;
      display: none;
    `;
    document.body.appendChild(this.overlayEl);
  }

  onHover(e) {
    const target = e.target;
    if (!target || !this.overlayEl) return;
    if (target.closest('#job-os-copilot-drawer, #job-os-copilot-handle, #job-os-inspector-card')) return;

    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName) || target.getAttribute('role') === 'combobox') {
      const labelInfo = extractSemanticLabel(target);
      const fakeFormField = {
        element: target,
        name: target.name || '',
        htmlId: target.id || '',
        autocomplete: target.autocomplete || '',
        ariaLabel: target.getAttribute('aria-label') || '',
        placeholder: target.placeholder || '',
        dataAutomationId: target.getAttribute('data-automation-id') || '',
        labelInfo,
        fieldType: target.type || target.tagName.toLowerCase(),
      };

      const result = classifyFormField(fakeFormField);

      this.overlayEl.innerHTML = `
        <div style="font-weight: 700; color: #60a5fa; margin-bottom: 4px;">🔍 Field Inspector</div>
        <div><strong>Key:</strong> <span style="color: #10b981;">${result.canonicalKey}</span></div>
        <div><strong>Confidence:</strong> ${result.confidence}% (${result.confidenceTier})</div>
        <div><strong>Label:</strong> ${labelInfo.raw || '(none)'}</div>
        <div><strong>Name / ID:</strong> ${target.name || target.id || '(none)'}</div>
        <div><strong>Sensitive:</strong> ${result.isSensitive ? '⚠️ YES (Firewalled)' : 'No'}</div>
      `;
      this.overlayEl.style.display = 'block';
    }
  }
}

export const globalFieldInspector = new FieldInspector();
