/**
 * Tests for trigger-publishing Edge Function (pacing, formatting, authentication, and execution).
 */
import { describe, it, expect } from "vitest";
import {
  checkPacing,
  formatTelegramPost,
  formatDiscordEmbed,
  formatBlueskyPost,
  formatDevtoArticle,
  formatMastodonPost,
  formatTwitterPost,
  formatPlatformList,
  normalizePlatformName,
  type PlatformConfig,
  type JobItem,
} from "./trigger-publishing/index.ts";

describe("trigger-publishing pacing and config validator", () => {
  const sampleConfig: PlatformConfig = {
    platform: "telegram",
    min_gap_minutes: 30,
    daily_cap: 5,
    active_start_hour: 7,
    active_end_hour: 22,
    enabled: true,
    published_today: 2,
    last_post_at: "2026-09-01T10:00:00.000Z",
  };

  it("permits posting when inside active hours and past min_gap", () => {
    const now = new Date("2026-09-01T10:45:00.000Z");
    const result = checkPacing(sampleConfig, now, false);
    expect(result.eligible).toBe(true);
    expect(result.resetPublishedToday).toBe(false);
  });

  it("blocks posting when min_gap_minutes has not elapsed", () => {
    const now = new Date("2026-09-01T10:15:00.000Z");
    const result = checkPacing(sampleConfig, now, false);
    expect(result.eligible).toBe(false);
    expect(result.reason).toContain("Minimum gap not elapsed");
  });

  it("blocks posting when daily cap is reached", () => {
    const cappedConfig: PlatformConfig = {
      ...sampleConfig,
      published_today: 5,
      daily_cap: 5,
    };
    const now = new Date("2026-09-01T12:00:00.000Z");
    const result = checkPacing(cappedConfig, now, false);
    expect(result.eligible).toBe(false);
    expect(result.reason).toContain("Daily cap reached");
  });

  it("resets published_today when last post occurred on a previous UTC day", () => {
    const yesterdayConfig: PlatformConfig = {
      ...sampleConfig,
      published_today: 5,
      daily_cap: 5,
      last_post_at: "2026-08-31T20:00:00.000Z",
    };
    const now = new Date("2026-09-01T08:00:00.000Z");
    const result = checkPacing(yesterdayConfig, now, false);
    expect(result.eligible).toBe(true);
    expect(result.resetPublishedToday).toBe(true);
    expect(result.effectivePublishedToday).toBe(0);
  });

  it("blocks posting when outside active UTC hours", () => {
    const now = new Date("2026-09-01T04:00:00.000Z");
    const result = checkPacing(sampleConfig, now, false);
    expect(result.eligible).toBe(false);
    expect(result.reason).toContain("Outside active hours");
  });

  it("overrides all pacing constraints when force is true", () => {
    const blockedConfig: PlatformConfig = {
      ...sampleConfig,
      published_today: 10,
      daily_cap: 5,
      last_post_at: "2026-09-01T03:59:00.000Z",
    };
    const now = new Date("2026-09-01T04:00:00.000Z");
    const result = checkPacing(blockedConfig, now, true);
    expect(result.eligible).toBe(true);
  });
});

describe("trigger-publishing platform formatters for 6 target channels", () => {
  const sampleJobs: JobItem[] = [
    {
      id: "123e4567-e89b-12d3-a456-426614174000",
      title: "Senior Backend Engineer",
      company: "Stripe",
      location_raw: "Dublin, Ireland",
      apply_url: "https://stripe.com/jobs/123",
      salary_raw: "€110,000 - €135,000",
      visa_sponsorship_verified: true,
      visa_types: ["Critical Skills Employment Permit"],
    },
    {
      id: "223e4567-e89b-12d3-a456-426614174001",
      title: "AI Research Scientist",
      company: "DeepMind",
      location_raw: "London, UK",
      apply_url: "https://deepmind.google/careers/456",
      visa_sponsorship_verified: true,
      visa_types: ["Skilled Worker Visa"],
    },
  ];

  it("formats Telegram markdown message with all jobs", () => {
    const text = formatTelegramPost(sampleJobs);
    expect(text).toContain("*Senior Backend Engineer* — Stripe");
    expect(text).toContain("📍 Dublin, Ireland");
    expect(text).toContain("Critical Skills Employment Permit");
    expect(text).toContain("[Apply Now](https://stripe.com/jobs/123)");
    expect(text).toContain("AI Research Scientist");
    expect(text).toContain("visalane.app");
  });

  it("formats Discord rich embed object", () => {
    const embed = formatDiscordEmbed(sampleJobs[0]);
    expect(embed.title).toBe("Senior Backend Engineer — Stripe");
    expect(embed.url).toBe("https://stripe.com/jobs/123");
    expect(embed.color).toBe(0x22c55e);
    expect(Array.isArray(embed.fields)).toBe(true);
  });

  it("formats Bluesky post within 300 characters", () => {
    const text = formatBlueskyPost(sampleJobs[0]);
    expect(text.length).toBeLessThanOrEqual(300);
    expect(text).toContain("Stripe is hiring: Senior Backend Engineer");
    expect(text).toContain("https://stripe.com/jobs/123");
  });

  it("formats Dev.to article with markdown frontmatter", () => {
    const article = formatDevtoArticle(sampleJobs);
    expect(article.title).toContain("Senior Backend Engineer @ Stripe");
    expect(article.body_markdown).toContain("## Verified Visa-Sponsored Engineering Roles");
    expect(article.body_markdown).toContain("Stripe");
    expect(article.body_markdown).toContain("DeepMind");
    expect(article.tags).toContain("softwareengineering");
  });

  it("formats Mastodon status within 500 characters", () => {
    const text = formatMastodonPost(sampleJobs[0]);
    expect(text.length).toBeLessThanOrEqual(500);
    expect(text).toContain("Senior Backend Engineer at Stripe");
    expect(text).toContain("#VisaSponsorship");
  });

  it("formats Twitter/X post adhering strictly to 280 character limit", () => {
    const text = formatTwitterPost(sampleJobs[0]);
    expect(text.length).toBeLessThanOrEqual(280);
    expect(text).toContain("Stripe");
    expect(text).toContain("Senior Backend Engineer");
  });

  it("normalizes platform names correctly", () => {
    expect(normalizePlatformName("X")).toBe("twitter");
    expect(normalizePlatformName("twitter")).toBe("twitter");
    expect(normalizePlatformName("dev_to")).toBe("devto");
    expect(normalizePlatformName("DEVTO")).toBe("devto");
    expect(normalizePlatformName("BLUESKY")).toBe("bluesky");
  });

  it("formats platform list with oxford comma conjunction", () => {
    const platforms = ["telegram", "discord", "bluesky", "devto", "mastodon", "twitter"];
    const formatted = formatPlatformList(platforms);
    expect(formatted).toBe("Telegram, Discord, Bluesky, Dev.to, Mastodon, and X");
  });
});
