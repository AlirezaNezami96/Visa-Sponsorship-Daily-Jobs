/**
 * diagnostics.js — Local Privacy-First Autofill Diagnostics Logger
 */

export class LocalDiagnosticsLogger {
  constructor() {
    this.records = [];
  }

  logRun({
    atsName = 'Generic',
    fieldCount = 0,
    filledCount = 0,
    aiCount = 0,
    skippedCount = 0,
    durationMs = 0,
  }) {
    const record = {
      timestamp: Date.now(),
      hostname: window.location.hostname,
      atsName,
      fieldCount,
      filledCount,
      aiCount,
      skippedCount,
      successRate: fieldCount > 0 ? Math.round((filledCount / fieldCount) * 100) : 100,
      durationMs,
    };

    this.records.push(record);
    if (this.records.length > 50) {
      this.records.shift();
    }

    try {
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        chrome.storage.local.set({ JOB_OS_DIAGNOSTICS: this.records });
      }
    } catch (_) {}

    return record;
  }
}

export const localDiagnostics = new LocalDiagnosticsLogger();
