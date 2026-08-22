/**
 * engine.js — Master Autofill Orchestrator
 */

import { GreenhouseAdapter } from './adapters/greenhouse.js';
import { LeverAdapter } from './adapters/lever.js';
import { AshbyAdapter } from './adapters/ashby.js';
import { WorkdayAdapter } from './adapters/workday.js';
import { LinkedInAdapter } from './adapters/linkedin.js';
import { GenericAdapter } from './adapters/generic.js';
import { AutofillOverlay } from './overlay.js';
import { attachPdfToFileInput, findResumeFileInput } from './files.js';

const ADAPTERS = [
  GreenhouseAdapter,
  LeverAdapter,
  AshbyAdapter,
  WorkdayAdapter,
  LinkedInAdapter,
  GenericAdapter,
];

export async function detectAndMountAutofill(apiBase = 'http://127.0.0.1:8000') {
  // Check if current page is an apply form
  const isApplyPage = (
    window.location.href.includes('/apply') ||
    window.location.href.includes('/application') ||
    window.location.hostname.includes('myworkdayjobs.com') ||
    document.querySelector('#application_form, .application-form, [data-testid="application-form"], [data-automation-id="workdayApplication"]') !== null
  );

  if (!isApplyPage) return;

  const activeAdapter = ADAPTERS.find((a) => a.matches()) || GenericAdapter;

  const overlay = new AutofillOverlay(activeAdapter.name, async () => {
    try {
      // 1. Fetch applicant profile
      const profileRes = await fetch(`${apiBase}/api/v1/profile`);
      if (!profileRes.ok) throw new Error('Could not load applicant profile from engine backend.');
      const profile = await profileRes.json();

      // 2. Fill form via active adapter
      const res = await activeAdapter.fillForm(profile, {}, (progress) => {
        overlay.updateProgress(progress.current, progress.total, progress.field);
      });

      overlay.showComplete(res.filled, res.skipped);
    } catch (err) {
      console.error('Autofill execution failed:', err);
      alert(`Autofill Error: ${err.message}`);
    }
  });

  overlay.mount();
}
