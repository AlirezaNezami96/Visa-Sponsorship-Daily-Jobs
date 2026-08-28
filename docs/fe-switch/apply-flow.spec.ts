import { test, expect } from '@playwright/test';

/**
 * Playwright E2E Test Suite for VisaLane Apply Flow (Live Mode, Mocks OFF)
 *
 * Runs against the seeded Supabase instance with VITE_USE_MOCKS=false.
 * Validates the full applicant flow:
 * 1. User authentication
 * 2. Resume parsing & structured data extraction
 * 3. Tailored resume generation + PDF preview iframe rendering
 * 4. Cover letter generation
 * 5. Outreach message generation
 * 6. Application completion
 * 7. Verification that "Applied" status appears in My Jobs dashboard
 */

const TEST_EMAIL = process.env.PLAYWRIGHT_TEST_EMAIL || 'test-applicant@visalane.online';
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_PASSWORD || 'SecretPassword123!';
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'https://visalane.online';

test.describe('VisaLane Full Apply Flow (Live Mode)', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to VisaLane web app
    await page.goto(BASE_URL);
  });

  test('completes full job application journey with live Edge Functions', async ({ page }) => {
    // 1. Sign In
    const loginButton = page.locator('button:has-text("Sign In"), a:has-text("Sign In")').first();
    if (await loginButton.isVisible()) {
      await loginButton.click();
      await page.fill('input[type="email"]', TEST_EMAIL);
      await page.fill('input[type="password"]', TEST_PASSWORD);
      await page.click('button[type="submit"]:has-text("Sign In"), button:has-text("Log In")');
      await page.waitForURL('**/dashboard**', { timeout: 15000 }).catch(() => {});
    }

    // 2. Upload / Parse Resume
    await page.goto(`${BASE_URL}/profile`);
    const uploadInput = page.locator('input[type="file"]');
    if (await uploadInput.isVisible()) {
      // Provide fixture resume
      await uploadInput.setInputFiles({
        name: 'resume.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from(
          'Alireza Nezami\nSenior Mobile Engineer\nEmail: test@example.com\n' +
          'Experience:\nTechCorp Inc (2021-Present) - Senior Android Developer\n' +
          'Skills: Kotlin, Flutter, Jetpack Compose, TypeScript'
        ),
      });
      // Wait for parse completion toast/status
      await expect(page.locator('text=Resume parsed successfully, text=Profile updated')).toBeVisible({
        timeout: 20000,
      });
    }

    // 3. Search & Select a Verified Job
    await page.goto(`${BASE_URL}/jobs`);
    const firstJobCard = page.locator('[data-testid="job-card"], .job-card').first();
    await expect(firstJobCard).toBeVisible({ timeout: 15000 });
    await firstJobCard.click();

    // 4. Open Apply with AI Modal
    const applyAiButton = page.locator('button:has-text("Apply with AI"), button:has-text("Tailor Application")');
    await expect(applyAiButton).toBeVisible();
    await applyAiButton.click();

    // 5. Generate Tailored Resume & Verify PDF Preview
    const tailorResumeTab = page.locator('button:has-text("Tailored Resume"), [role="tab"]:has-text("Resume")');
    await tailorResumeTab.click();

    const generateResumeBtn = page.locator('button:has-text("Generate Tailored Resume"), button:has-text("Tailor Resume")');
    if (await generateResumeBtn.isVisible()) {
      await generateResumeBtn.click();
    }

    // Assert that the signed PDF preview iframe or viewer loads
    const pdfFrame = page.locator('iframe[src*="supabase"], [data-testid="pdf-preview-frame"]');
    await expect(pdfFrame).toBeVisible({ timeout: 30000 });

    // 6. Generate Cover Letter
    const coverLetterTab = page.locator('button:has-text("Cover Letter"), [role="tab"]:has-text("Cover Letter")');
    await coverLetterTab.click();

    const generateCoverBtn = page.locator('button:has-text("Generate Cover Letter")');
    if (await generateCoverBtn.isVisible()) {
      await generateCoverBtn.click();
    }

    await expect(page.locator('textarea, [data-testid="cover-letter-preview"]')).toBeVisible({ timeout: 30000 });

    // 7. Generate Outreach Messages
    const outreachTab = page.locator('button:has-text("Outreach"), [role="tab"]:has-text("Outreach")');
    if (await outreachTab.isVisible()) {
      await outreachTab.click();
      const generateOutreachBtn = page.locator('button:has-text("Generate Outreach")');
      if (await generateOutreachBtn.isVisible()) {
        await generateOutreachBtn.click();
      }
      await expect(page.locator('text=LinkedIn, text=Subject')).toBeVisible({ timeout: 30000 });
    }

    // 8. Complete Application
    const markAppliedBtn = page.locator('button:has-text("Mark as Applied"), button:has-text("Complete Application")');
    await expect(markAppliedBtn).toBeVisible();
    await markAppliedBtn.click();

    // 9. Verify in My Jobs Dashboard
    await page.goto(`${BASE_URL}/my-jobs`);
    await expect(page.locator('text=Applied, [data-status="applied"]')).toBeVisible({ timeout: 15000 });
  });
});
