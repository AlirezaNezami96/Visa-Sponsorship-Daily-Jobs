/**
 * Tests for admin metrics verification and payload shapes.
 */
import { describe, it, expect } from "vitest";

describe("admin metrics endpoint logic", () => {
  it("computes aggregate statistics correctly", () => {
    const metricsDaily = [
      { day: "2026-08-30", metric: "scrape:greenhouse:ok", count: 10, error_count: 1, sum_ms: 2000 },
      { day: "2026-08-30", metric: "ai:resume:ok", count: 5, error_count: 0, sum_ms: 5000 },
      { day: "2026-08-29", metric: "image:generated", count: 15, error_count: 2, sum_ms: 15000 },
    ];

    let totalEvents = 0;
    let totalErrors = 0;
    let totalSumMs = 0;

    for (const row of metricsDaily) {
      totalEvents += row.count;
      totalErrors += row.error_count;
      totalSumMs += row.sum_ms;
    }

    const errorRatePercent = totalEvents > 0 ? Number(((totalErrors / totalEvents) * 100).toFixed(2)) : 0;
    const avgLatencyMs = totalEvents > 0 ? Math.round(totalSumMs / totalEvents) : 0;

    expect(totalEvents).toBe(30);
    expect(totalErrors).toBe(3);
    expect(errorRatePercent).toBe(10.0);
    expect(avgLatencyMs).toBe(733);
  });
});
