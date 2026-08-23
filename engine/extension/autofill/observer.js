/**
 * observer.js — Dynamic DOM MutationObserver & SPA Route Change Tracker
 */

export class DynamicDomObserver {
  constructor(onNewFieldsDetected, onRouteChanged) {
    this.onNewFieldsDetected = onNewFieldsDetected;
    this.onRouteChanged = onRouteChanged;
    this.observer = null;
    this.debounceTimer = null;
    this.currentUrl = window.location.href;
    this.isObserving = false;
  }

  start() {
    if (this.isObserving) return;
    this.isObserving = true;

    // 1. Observe DOM Mutations
    this.observer = new MutationObserver((mutations) => {
      let hasAddedNodes = false;
      for (const m of mutations) {
        if (m.addedNodes && m.addedNodes.length > 0) {
          hasAddedNodes = true;
          break;
        }
      }

      if (hasAddedNodes) {
        clearTimeout(this.debounceTimer);
        this.debounceTimer = setTimeout(() => {
          if (this.onNewFieldsDetected) {
            this.onNewFieldsDetected();
          }
        }, 200);
      }
    });

    this.observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
    });

    // 2. Intercept History API (pushState, replaceState) for SPA navigations
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;
    const self = this;

    history.pushState = function (...args) {
      originalPushState.apply(this, args);
      self.checkUrlChange();
    };

    history.replaceState = function (...args) {
      originalReplaceState.apply(this, args);
      self.checkUrlChange();
    };

    window.addEventListener('popstate', () => this.checkUrlChange());
    window.addEventListener('hashchange', () => this.checkUrlChange());
  }

  checkUrlChange() {
    if (window.location.href !== this.currentUrl) {
      this.currentUrl = window.location.href;
      if (this.onRouteChanged) {
        this.onRouteChanged(this.currentUrl);
      }
    }
  }

  stop() {
    if (this.observer) {
      this.observer.disconnect();
      this.observer = null;
    }
    clearTimeout(this.debounceTimer);
    this.isObserving = false;
  }
}
