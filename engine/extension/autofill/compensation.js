/**
 * compensation.js — Multi-Currency & Multi-Period Compensation Engine
 *
 * Target: 3000 USD gross monthly.
 * Automatically converts currency and period (hour, day, week, month, year, b2b).
 */

const DEFAULT_FX = {
  USD: 1.0,
  EUR: 0.92,
  GBP: 0.78,
  PLN: 4.00,
  CAD: 1.36,
  TRY: 41.0,
  INR: 83.0,
  AUD: 1.52,
};

export function detectCurrency(text) {
  const t = (text || '').toLowerCase();
  if (t.includes('eur') || t.includes('€') || t.includes('euro')) return 'EUR';
  if (t.includes('gbp') || t.includes('£') || t.includes('pound')) return 'GBP';
  if (t.includes('pln') || t.includes('zł') || t.includes('zloty')) return 'PLN';
  if (t.includes('cad') || t.includes('c$')) return 'CAD';
  if (t.includes('try') || t.includes('₺') || t.includes(' tl') || t.includes('lira')) return 'TRY';
  if (t.includes('inr') || t.includes('₹') || t.includes('rupee')) return 'INR';
  if (t.includes('aud') || t.includes('a$')) return 'AUD';
  return 'USD';
}

export function detectPeriod(text) {
  const t = (text || '').toLowerCase();
  if (t.includes('hour') || t.includes('/hr') || t.includes('hourly')) return 'hour';
  if (t.includes('day') || t.includes('/day') || t.includes('daily')) return 'day';
  if (t.includes('week') || t.includes('/wk') || t.includes('weekly')) return 'week';
  if (t.includes('year') || t.includes('annual') || t.includes('annum') || t.includes('/yr') || t.includes('p.a') || t.includes('pa')) return 'year';
  return 'month';
}

export function calculateTargetCompensation(textContext, profile) {
  const fxTable = profile?.compensation?.fx_fallback || DEFAULT_FX;
  const monthlyUsd = profile?.compensation?.monthly_usd || 3000;
  const hoursPerMonth = profile?.compensation?.hours_per_month || 173.33;

  const currency = detectCurrency(textContext);
  const period = detectPeriod(textContext);
  const fxRate = fxTable[currency] || 1.0;

  let baseUsd = monthlyUsd;
  let isFractional = false;

  switch (period) {
    case 'hour':
      baseUsd = monthlyUsd / hoursPerMonth; // 3000 / 173.33 ≈ 17.3079
      isFractional = true;
      break;
    case 'day':
      baseUsd = (monthlyUsd / hoursPerMonth) * 8; // ≈ 138.46
      isFractional = true;
      break;
    case 'week':
      baseUsd = monthlyUsd / (52 / 12); // ≈ 692.31
      isFractional = true;
      break;
    case 'year':
      baseUsd = monthlyUsd * 12; // 36,000
      isFractional = false;
      break;
    case 'month':
    default:
      baseUsd = monthlyUsd; // 3,000
      isFractional = false;
      break;
  }

  let converted = baseUsd * fxRate;

  // Handle "in thousands" or "k" notation
  const t = (textContext || '').toLowerCase();
  if (t.includes('in thousand') || t.includes('thousands') || t.includes('(k)') || t.includes('in k')) {
    converted = converted / 1000;
    isFractional = true;
  }

  const finalAmount = isFractional ? Math.round(converted * 100) / 100 : Math.round(converted);

  return {
    amount: finalAmount,
    currency,
    period,
    formatted: isFractional ? finalAmount.toFixed(2) : String(finalAmount),
    display: `${finalAmount} ${currency} / ${period}`,
  };
}
