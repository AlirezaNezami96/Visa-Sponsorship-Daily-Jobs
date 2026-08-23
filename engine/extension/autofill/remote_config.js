/**
 * remote_config.js — Versioned Compatibility Configuration Manager with Offline Fallback
 */

const CONFIG_STORAGE_KEY = 'JOB_OS_AUTOFILL_CONFIG';
const CONFIG_CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

const BUNDLED_DEFAULT_CONFIG = {
  version: 1,
  generatedAt: '2026-08-22T00:00:00Z',
  platforms: {
    greenhouse: {
      name: 'Greenhouse',
      urlPatterns: ['*://boards.greenhouse.io/*', '*://job-boards.greenhouse.io/*'],
      fields: {
        first_name: { selectors: ['#first_name', "input[name='first_name']"] },
        last_name: { selectors: ['#last_name', "input[name='last_name']"] },
        email: { selectors: ['#email', "input[name='email']"] },
        phone: { selectors: ['#phone', "input[name='phone']"] },
        city: { selectors: ['#job_application_location', "input[name*='location']"] },
        resume_file: { selectors: ['#resume_file', "input[name='resume']", "input[type='file']"] },
      },
    },
    workday: {
      name: 'Workday',
      urlPatterns: ['*://*.myworkdayjobs.com/*', '*://*.myworkday.com/*'],
      fields: {
        first_name: { selectors: ["[data-automation-id='legalNameSection_firstName']"] },
        last_name: { selectors: ["[data-automation-id='legalNameSection_lastName']"] },
        email: { selectors: ["[data-automation-id='email']"] },
        phone: { selectors: ["[data-automation-id='phone-number']"] },
        city: { selectors: ["[data-automation-id='addressSection_city']"] },
        resume_file: { selectors: ["[data-automation-id='file-upload-drop-zone'] input[type='file']"] },
      },
    },
    lever: {
      name: 'Lever',
      urlPatterns: ['*://jobs.lever.co/*'],
      fields: {
        full_name: { selectors: ["input[name='name']"] },
        email: { selectors: ["input[name='email']"] },
        phone: { selectors: ["input[name='phone']"] },
        current_company: { selectors: ["input[name='org']"] },
        city: { selectors: ["input[name='location']"] },
        resume_file: { selectors: ["input[name='resume']"] },
      },
    },
    ashby: {
      name: 'Ashby',
      urlPatterns: ['*://jobs.ashbyhq.com/*'],
      fields: {
        first_name: { selectors: ["input[name='firstName']", "[data-testid='field-firstName'] input"] },
        last_name: { selectors: ["input[name='lastName']", "[data-testid='field-lastName'] input"] },
        email: { selectors: ["input[name='email']", "[data-testid='field-email'] input"] },
        phone: { selectors: ["input[name='phone']", "[data-testid='field-phone'] input"] },
      },
    },
  },
};

export class RemoteConfigManager {
  constructor() {
    this.config = BUNDLED_DEFAULT_CONFIG;
    this.loadedAt = 0;
  }

  /**
   * Validates that config is safe data (no executable scripts, valid selector strings).
   */
  validateConfig(data) {
    if (!data || typeof data !== 'object') return false;
    if (typeof data.version !== 'number') return false;
    if (!data.platforms || typeof data.platforms !== 'object') return false;

    // Check that every selector is a safe string without script injection
    for (const [platformId, platform] of Object.entries(data.platforms)) {
      if (platform.fields && typeof platform.fields === 'object') {
        for (const [fieldKey, fieldDef] of Object.entries(platform.fields)) {
          if (Array.isArray(fieldDef.selectors)) {
            for (const sel of fieldDef.selectors) {
              if (typeof sel !== 'string' || sel.includes('<script') || sel.includes('javascript:')) {
                return false;
              }
            }
          }
        }
      }
    }
    return true;
  }

  /**
   * Fetches latest configuration from background proxy or local cache.
   */
  async getEffectiveConfig() {
    if (this.config && Date.now() - this.loadedAt < CONFIG_CACHE_TTL_MS && this.loadedAt > 0) {
      return this.config;
    }

    // 1. Try chrome.storage local cache
    try {
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        const stored = await chrome.storage.local.get([CONFIG_STORAGE_KEY]);
        if (stored && stored[CONFIG_STORAGE_KEY]) {
          const { timestamp, data } = stored[CONFIG_STORAGE_KEY];
          if (Date.now() - timestamp < CONFIG_CACHE_TTL_MS && this.validateConfig(data)) {
            this.config = data;
            this.loadedAt = timestamp;
            return data;
          }
        }
      }
    } catch (_) {}

    // 2. Fetch from backend API via background worker proxy
    try {
      const resp = await chrome.runtime.sendMessage({ action: 'GET_AUTOFILL_CONFIG' });
      if (resp && resp.success && resp.config && this.validateConfig(resp.config)) {
        this.config = resp.config;
        this.loadedAt = Date.now();
        if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
          chrome.storage.local.set({
            [CONFIG_STORAGE_KEY]: { timestamp: this.loadedAt, data: resp.config },
          });
        }
        return resp.config;
      }
    } catch (_) {}

    // 3. Fallback to bundled in-memory config
    this.config = BUNDLED_DEFAULT_CONFIG;
    this.loadedAt = Date.now();
    return BUNDLED_DEFAULT_CONFIG;
  }

  /**
   * Returns field hints for a specific platform ID.
   */
  async getPlatformHints(platformId) {
    const config = await this.getEffectiveConfig();
    if (config && config.platforms && config.platforms[platformId]) {
      return config.platforms[platformId].fields || {};
    }
    return {};
  }
}

export const remoteConfigManager = new RemoteConfigManager();
