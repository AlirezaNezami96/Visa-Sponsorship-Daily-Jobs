/**
 * engine.js — Master Copilot Bootstrapper & Lifecycle Controller
 */

import { isApplicationFormPresent } from './detect.js';
import { defaultAdapterRegistry } from './adapters/registry.js';
import { CopilotHandle } from './handle.js';
import { CopilotDrawer } from './drawer.js';
import { runAutofillSequence } from './runner.js';
import { DynamicDomObserver } from './observer.js';

function extractCurrentJobData() {
  const comp = document.querySelector('.company-name, [data-automation-id="companyName"], .app-title, .posting-headline h2, .topcard__org-name-link')?.textContent?.trim() || '';
  const title = document.querySelector('h1, .job-title, [data-automation-id="jobTitle"], .posting-headline h2, .top-card-layout__title')?.textContent?.trim() || 'Software Engineer';
  return {
    pageUrl: window.location.href,
    companyName: comp && !/^(company|unknown)$/i.test(comp) ? comp : '',
    jobTitle: title,
    jobDescription: document.body.innerText?.slice(0, 5000) || '',
  };
}

export async function detectAndMountAutofill() {
  // Prevent duplicate mounts on the same frame
  if (window.__JOB_OS_COPILOT__) return;

  const isFormHere = isApplicationFormPresent(document);
  if (!isFormHere) return;

  window.__JOB_OS_COPILOT__ = true;
  const adapter = defaultAdapterRegistry.resolveAdapter(window.location.href, document);
  const atsName = adapter.name;

  let drawer = null;
  const handle = new CopilotHandle(() => {
    if (drawer) drawer.toggle();
  });

  drawer = new CopilotDrawer(
    atsName,
    async (session) => {
      const jobData = extractCurrentJobData();
      await runAutofillSequence(drawer, jobData, session);
    },
    () => extractCurrentJobData()
  );

  await handle.mount();
  drawer.mount();

  // Initialize Dynamic DOM Observer for conditional questions & SPA routes
  const domObserver = new DynamicDomObserver(
    () => {
      // If drawer is open and not currently filling, refresh discovered fields
      if (drawer && drawer.session && drawer.session.status !== 'filling') {
        const jobData = extractCurrentJobData();
        // Optional non-intrusive refresh
      }
    },
    (newUrl) => {
      // SPA route changed
      console.debug('[JobOS] SPA Route changed to:', newUrl);
    }
  );
  domObserver.start();
}
