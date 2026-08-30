import { describe, it, expect, beforeEach } from "vitest";
import {
  isValidEmail,
  isValidOtp,
  normalizeEmail,
  generateSecureOtp,
  hashOtp,
  renderOtpEmailHtml,
  OtpRateLimiter,
  DEFAULT_RATE_LIMITS,
} from "./auth-otp.ts";

describe("Auth & OTP Service Utilities", () => {
  describe("Email Normalization & Validation", () => {
    it("normalizes mixed-case and whitespace-padded emails", () => {
      expect(normalizeEmail("  Alireza.Nezami75@GMAIL.COM  ")).toBe("alireza.nezami75@gmail.com");
      expect(normalizeEmail("")).toBe("");
      expect(normalizeEmail(null as unknown as string)).toBe("");
      expect(normalizeEmail(undefined as unknown as string)).toBe("");
    });

    it("accepts valid RFC 5322 standard email addresses", () => {
      const validEmails = [
        "user@example.com",
        "first.last@company.org",
        "user+tag@domain.co.uk",
        "dev_123@sub.domain.io",
        "a@b.de",
        "12345@numbers.net",
      ];
      for (const email of validEmails) {
        expect(isValidEmail(email), `Expected '${email}' to be valid`).toBe(true);
      }
    });

    it("rejects invalid, malformed, or unsafe email addresses", () => {
      const invalidEmails = [
        "",
        "   ",
        "notanemail",
        "@domain.com",
        "user@",
        "user@.com",
        "user@domain",
        "user@domain..com",
        "user name@domain.com",
        "user@domain.c",
        "a".repeat(250) + "@domain.com", // > 254 characters
        null,
        undefined,
      ];
      for (const email of invalidEmails) {
        expect(isValidEmail(email as string), `Expected '${email}' to be invalid`).toBe(false);
      }
    });
  });

  describe("OTP Format Validation", () => {
    it("accepts valid 6-digit OTP codes", () => {
      expect(isValidOtp("123456")).toBe(true);
      expect(isValidOtp("000000")).toBe(true);
      expect(isValidOtp("999999")).toBe(true);
      expect(isValidOtp("012345")).toBe(true);
      expect(isValidOtp(" 654321 ")).toBe(true); // handles whitespace trimming
    });

    it("rejects invalid OTP codes of wrong length or non-digit characters", () => {
      const invalidOtps = [
        "",
        "   ",
        "123",
        "12345",
        "1234567",
        "abcdef",
        "12a456",
        "123 45",
        "-12345",
        "12.345",
        null,
        undefined,
      ];
      for (const otp of invalidOtps) {
        expect(isValidOtp(otp as string), `Expected '${otp}' to be invalid`).toBe(false);
      }
    });
  });

  describe("Cryptographic OTP Generation & Hashing", () => {
    it("generates a 6-digit string token with leading zeros if needed", () => {
      for (let i = 0; i < 50; i++) {
        const otp = generateSecureOtp();
        expect(otp).toHaveLength(6);
        expect(/^\d{6}$/.test(otp)).toBe(true);
      }
    });

    it("generates consistent 64-character SHA-256 hashes", async () => {
      const token = "849201";
      const hash1 = await hashOtp(token);
      const hash2 = await hashOtp(token);
      expect(hash1).toHaveLength(64);
      expect(hash1).toBe(hash2);

      const diffHash = await hashOtp("849202");
      expect(diffHash).not.toBe(hash1);
    });
  });

  describe("Rate Limiting & Brute-Force Protection", () => {
    let limiter: OtpRateLimiter;
    const testKey = "email:user@example.com";
    const testNow = 1700000000000;

    beforeEach(() => {
      limiter = new OtpRateLimiter();
    });

    it("allows initial request and enforces cooldown period", () => {
      // 1. Initial request allowed
      const check1 = limiter.checkRequestLimit(testKey, testNow);
      expect(check1.allowed).toBe(true);

      // Record request
      limiter.recordRequest(testKey, "hash_abc", testNow);

      // 2. Immediate second request within 60s cooldown is rejected
      const check2 = limiter.checkRequestLimit(testKey, testNow + 30 * 1000);
      expect(check2.allowed).toBe(false);
      expect(check2.reason).toBe("cooldown");
      expect(check2.retryAfterSeconds).toBe(30);

      // 3. Request after 61s cooldown is allowed
      const check3 = limiter.checkRequestLimit(testKey, testNow + 61 * 1000);
      expect(check3.allowed).toBe(true);
    });

    it("enforces maximum burst requests per window", () => {
      let currentTime = testNow;

      // Make 5 requests spaced 65s apart (respecting cooldown)
      for (let i = 0; i < 5; i++) {
        const check = limiter.checkRequestLimit(testKey, currentTime);
        expect(check.allowed).toBe(true);
        limiter.recordRequest(testKey, `hash_${i}`, currentTime);
        currentTime += 65 * 1000;
      }

      // 6th request within 10-minute window is rejected
      const check6 = limiter.checkRequestLimit(testKey, currentTime);
      expect(check6.allowed).toBe(false);
      expect(check6.reason).toBe("window_limit");
    });

    it("locks session after 5 failed verification attempts (brute force protection)", () => {
      limiter.recordRequest(testKey, "valid_hash", testNow);

      // 4 wrong attempts
      for (let i = 1; i <= 4; i++) {
        const failure = limiter.recordVerifyFailure(testKey, testNow);
        expect(failure.locked).toBe(false);
        expect(failure.remainingAttempts).toBe(5 - i);
      }

      // 5th wrong attempt triggers lockout
      const finalFailure = limiter.recordVerifyFailure(testKey, testNow);
      expect(finalFailure.locked).toBe(true);
      expect(finalFailure.remainingAttempts).toBe(0);

      // New request while locked is rejected
      const checkLocked = limiter.checkRequestLimit(testKey, testNow + 1000);
      expect(checkLocked.allowed).toBe(false);
      expect(checkLocked.reason).toBe("locked");
    });

    it("clearing session resets limits and locks", () => {
      limiter.recordRequest(testKey, "hash_123", testNow);
      limiter.clearSession(testKey);

      const check = limiter.checkRequestLimit(testKey, testNow + 5000);
      expect(check.allowed).toBe(true);
    });
  });

  describe("Branded Email Template Rendering", () => {
    it("renders clean HTML containing token and VisaLane branding without raw template syntax", () => {
      const token = "739201";
      const html = renderOtpEmailHtml(token, {
        siteUrl: "https://visalane.online",
        appName: "VisaLane",
      });

      expect(html).toContain("739201");
      expect(html).toContain("VisaLane");
      expect(html).toContain("https://visalane.online");
      expect(html).toContain("<!DOCTYPE html>");
      expect(html).not.toContain("{{");
      expect(html).not.toContain("}}");
    });
  });
});
