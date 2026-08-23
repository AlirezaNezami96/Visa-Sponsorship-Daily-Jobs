/**
 * registry.js — ATS Adapter Registry & Priority Resolver
 */

import { WorkdayAdapter } from './workday.js';
import { GreenhouseAdapter } from './greenhouse.js';
import { LeverAdapter } from './lever.js';
import { AshbyAdapter } from './ashby.js';
import { IcimsAdapter } from './icims.js';
import { TaleoAdapter } from './taleo.js';
import { AvatureAdapter } from './avature.js';
import { SmartRecruitersAdapter } from './smartrecruiters.js';
import { AdpAdapter } from './adp.js';
import { LinkedInAdapter } from './linkedin.js';
import { IndeedAdapter } from './indeed.js';
import { GenericAdapter } from './generic.js';

export class AtsAdapterRegistry {
  constructor() {
    this.adapters = [
      new WorkdayAdapter(),
      new GreenhouseAdapter(),
      new LeverAdapter(),
      new AshbyAdapter(),
      new IcimsAdapter(),
      new TaleoAdapter(),
      new AvatureAdapter(),
      new SmartRecruitersAdapter(),
      new AdpAdapter(),
      new LinkedInAdapter(),
      new IndeedAdapter(),
      new GenericAdapter(), // Universal fallback
    ];
  }

  /**
   * Resolves the primary matching adapter for the given URL and document.
   */
  resolveAdapter(url = window.location.href, doc = document) {
    for (const adapter of this.adapters) {
      if (adapter.id !== 'generic' && adapter.matches(url, doc)) {
        return adapter;
      }
    }
    // Return universal generic adapter
    return this.adapters.find((a) => a.id === 'generic') || new GenericAdapter();
  }
}

export const defaultAdapterRegistry = new AtsAdapterRegistry();
