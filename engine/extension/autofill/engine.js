/**
 * engine.js — Master Copilot Bootstrapper & Lifecycle Controller
 */

import { isApplicationFormPresent } from './detect.js';
import { CopilotHandle } from './handle.js';
import { CopilotDrawer } from './drawer.js';
import { runAutofillSequence } from './runner.js';

function detectAtsName() {
  const host = window.location.hostname.toLowerCase();
  if (host.includes('greenhouse.io') || document.querySelector('#application_form')) return 'Greenhouse';
  if (host.includes('lever.co') || document.querySelector('.application-form')) return 'Lever';
  if (host.includes('ashbyhq.com') || document.querySelector('[data-testid="application-form"]')) return 'Ashby';
  if (host.includes('myworkday') || document.querySelector('[data-automation-id="workdayApplication"]')) return 'Workday';
  if (host.includes('linkedin.com')) return 'LinkedIn Easy Apply';
  if (host.includes('smartrecruiters.com')) return 'SmartRecruiters';
  if (host.includes('workable.com')) return 'Workable';
  return 'Application Form';
}

export async function detectAndMountAutofill() {
  // Prevent duplicate mounts on the same frame
  if (window.__JOB_OS_COPILOT__) return;

  const isFormHere = isApplicationFormPresent(document);
  if (!isFormHere) return;

  window.__JOB_OS_COPILOT__ = true;
  const atsName = detectAtsName();

  let drawer = null;
  const handle = new CopilotHandle(() => {
    if (drawer) drawer.toggle();
  });

  drawer = new CopilotDrawer(atsName, async () => {
    // Extract job details from page context if available
    const jobData = {
      pageUrl: window.location.href,
      companyName: document.querySelector('.company-name, [data-automation-id="companyName"]')?.textContent?.trim() || 'Company',
      jobTitle: document.querySelector('h1, .job-title, [data-automation-id="jobTitle"]')?.textContent?.trim() || 'Software Engineer',
      jobDescription: document.body.innerText?.slice(0, 5000) || '',
    };

    await runAutofillSequence(drawer, jobData);
  });

  await handle.mount();
  drawer.mount();
}
