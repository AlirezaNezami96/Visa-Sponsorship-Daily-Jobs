/**
 * VisaLane 1:1 Live Backend Adapter
 * Drop-in replacement for `global-job-pass/src/services/api.ts`.
 *
 * Direct communication with Supabase PostgREST and Edge Functions:
 * - PostgREST for public search & user RLS tables (profiles, saved_jobs, applications, alerts).
 * - Edge Functions for AI actions (parse-resume, generate-tailored-resume,
 *   generate-cover-letter, generate-outreach-messages, complete-application, usage-limits, feedback).
 * - Automatic 1x retry on transient network failures.
 * - HTTP 402 intercepted to trigger plan upgrade modals.
 * - PDF signed URLs consumed for inline previews & downloads.
 */

import { createClient, SupabaseClient, User } from '@supabase/supabase-js';

// Environment configuration
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || '';
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || '';
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  console.warn('VisaLane: Supabase URL or Anon Key is missing. Check your .env file.');
}

export const supabase: SupabaseClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Custom Error types
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string = 'api_error',
    public status: number = 500,
    public details?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class QuotaExceededError extends ApiError {
  constructor(message: string = 'Daily usage limit reached. Please upgrade to Pro.') {
    super(message, 'quota_exceeded', 402);
    this.name = 'QuotaExceededError';
  }
}

// Network retry helper
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  retries: number = 1,
  delayMs: number = 500
): Promise<T> {
  try {
    return await fn();
  } catch (err: unknown) {
    if (retries > 0 && !(err instanceof QuotaExceededError)) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      return fetchWithRetry(fn, retries - 1, delayMs * 2);
    }
    throw err;
  }
}

// Edge Function caller helper
async function callEdgeFunction<T = Record<string, unknown>>(
  functionName: string,
  body: Record<string, unknown> = {},
  method: 'POST' | 'GET' = 'POST'
): Promise<T> {
  return fetchWithRetry(async () => {
    const { data: sessionData } = await supabase.auth.getSession();
    const token = sessionData.session?.access_token;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      apikey: SUPABASE_ANON_KEY,
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const options: RequestInit = {
      method,
      headers,
    };

    if (method === 'POST') {
      options.body = JSON.stringify(body);
    }

    const url = `${SUPABASE_URL}/functions/v1/${functionName}`;
    const response = await fetch(url, options);

    if (response.status === 402) {
      const errorData = await response.json().catch(() => ({}));
      throw new QuotaExceededError(errorData?.error?.message || 'Daily limit reached');
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const code = errorData?.error?.code || `http_${response.status}`;
      const message = errorData?.error?.message || response.statusText || 'Request failed';
      throw new ApiError(message, code, response.status, errorData);
    }

    return (await response.json()) as T;
  });
}

// ---------------------------------------------------------------------------
// 1. Auth & Profiles
// ---------------------------------------------------------------------------

export async function getCurrentUser(): Promise<User | null> {
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) return null;
  return data.user;
}

export async function getUserProfile() {
  const user = await getCurrentUser();
  if (!user) return null;

  const { data, error } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', user.id)
    .maybeSingle();

  if (error) throw new ApiError(error.message, error.code, 400);
  return data;
}

export async function updateUserProfile(updates: Record<string, unknown>) {
  const user = await getCurrentUser();
  if (!user) throw new ApiError('Not authenticated', 'unauthorized', 401);

  const { data, error } = await supabase
    .from('profiles')
    .update({ ...updates, updated_at: new Date().toISOString() })
    .eq('id', user.id)
    .select()
    .single();

  if (error) throw new ApiError(error.message, error.code, 400);
  return data;
}

// ---------------------------------------------------------------------------
// 2. Job Search & Catalog (PostgREST)
// ---------------------------------------------------------------------------

export interface JobSearchParams {
  query?: string;
  location?: string;
  country?: string;
  roleLevel?: string;
  workMode?: string;
  verifiedOnly?: boolean;
  minConfidence?: number;
  limit?: number;
  offset?: number;
}

export async function searchJobs(params: JobSearchParams = {}) {
  return fetchWithRetry(async () => {
    let query = supabase
      .from('jobs')
      .select('*, companies(*), job_people(*)', { count: 'exact' })
      .eq('is_active', true)
      .order('scraped_at', { ascending: false });

    if (params.query) {
      query = query.or(`title.ilike.%${params.query}%,description_text.ilike.%${params.query}%`);
    }
    if (params.country) {
      query = query.eq('country', params.country);
    }
    if (params.location) {
      query = query.ilike('location_raw', `%${params.location}%`);
    }
    if (params.workMode) {
      query = query.eq('work_mode', params.workMode);
    }
    if (params.roleLevel) {
      query = query.eq('role_level', params.roleLevel);
    }
    if (params.verifiedOnly) {
      query = query.eq('visa_sponsorship_verified', true);
    }
    if (typeof params.minConfidence === 'number' && params.minConfidence > 0) {
      query = query.gte('visa_sponsorship_confidence', params.minConfidence);
    }

    const limit = params.limit || 20;
    const offset = params.offset || 0;
    query = query.range(offset, offset + limit - 1);

    const { data, error, count } = await query;
    if (error) throw new ApiError(error.message, error.code, 400);

    return {
      jobs: data || [],
      totalCount: count || 0,
      hasMore: (count || 0) > offset + limit,
    };
  });
}

export async function getJob(id: string) {
  return fetchWithRetry(async () => {
    const { data, error } = await supabase
      .from('jobs')
      .select('*, companies(*), job_people(*)')
      .eq('id', id)
      .single();

    if (error) throw new ApiError(error.message, error.code, 404);
    return data;
  });
}

// ---------------------------------------------------------------------------
// 3. Resume Upload & Structured Parsing
// ---------------------------------------------------------------------------

export async function uploadAndParseResume(file: File, extractedText?: string) {
  const user = await getCurrentUser();
  if (!user) throw new ApiError('Not authenticated', 'unauthorized', 401);

  const fileExt = file.name.split('.').pop() || 'txt';
  const filePath = `${user.id}/${Date.now()}_${file.name.replace(/[^a-zA-Z0-9._-]/g, '_')}`;

  // 1. Upload to Supabase Storage `resumes` bucket
  const { error: uploadError } = await supabase.storage
    .from('resumes')
    .upload(filePath, file, { upsert: true });

  if (uploadError) {
    throw new ApiError(`Failed to upload resume: ${uploadError.message}`, 'upload_failed', 400);
  }

  // 2. Call parse-resume Edge Function
  const payload: Record<string, unknown> = {
    storage_path: `resumes/${filePath}`,
  };
  if (extractedText && extractedText.trim().length >= 20) {
    payload['resume_text'] = extractedText;
  }

  const result = await callEdgeFunction<{
    output: Record<string, unknown>;
    document_id?: string;
  }>('parse-resume', payload);

  return {
    storagePath: filePath,
    parsedData: result.output,
    documentId: result.document_id,
  };
}

// ---------------------------------------------------------------------------
// 4. AI Generation Endpoints (Tailored Resume, Cover Letter, Outreach)
// ---------------------------------------------------------------------------

export interface GenerateTailoredResumeArgs {
  resumeId: string;
  jobId: string;
  formatPreference?: 'own' | 'professional';
}

export interface GeneratedDocumentResponse {
  output: Record<string, unknown>;
  document_id: string;
  pdf_url?: string;
  pdf_path?: string;
  idempotent?: boolean;
}

export async function generateTailoredResume(args: GenerateTailoredResumeArgs) {
  return callEdgeFunction<GeneratedDocumentResponse>('generate-tailored-resume', {
    resume_id: args.resumeId,
    job_id: args.jobId,
    format_preference: args.formatPreference || 'professional',
  });
}

export interface GenerateCoverLetterArgs {
  resumeId: string;
  jobId: string;
  tone?: 'confident' | 'enthusiastic' | 'concise';
}

export async function generateCoverLetter(args: GenerateCoverLetterArgs) {
  return callEdgeFunction<GeneratedDocumentResponse>('generate-cover-letter', {
    resume_id: args.resumeId,
    job_id: args.jobId,
    tone: args.tone || 'confident',
  });
}

export interface GenerateOutreachMessagesArgs {
  resumeId: string;
  jobId: string;
  tone?: 'warm' | 'concise' | 'formal';
}

export async function generateOutreachMessages(args: GenerateOutreachMessagesArgs) {
  return callEdgeFunction<{
    output: {
      linkedin_message: string;
      email_subject: string;
      email_body: string;
    };
    document_id: string;
  }>('generate-outreach-messages', {
    resume_id: args.resumeId,
    job_id: args.jobId,
    tone: args.tone || 'warm',
  });
}

// ---------------------------------------------------------------------------
// 5. Complete Application Flow
// ---------------------------------------------------------------------------

export interface CompleteApplicationArgs {
  jobId: string;
  resumeId?: string;
  tailoredResumeDocumentId?: string;
  coverLetterDocumentId?: string;
  appliedVia?: string;
  notes?: string;
}

export async function completeApplication(args: CompleteApplicationArgs) {
  return callEdgeFunction<{ application_id: string; status: string }>(
    'complete-application',
    {
      job_id: args.jobId,
      resume_id: args.resumeId,
      tailored_resume_document_id: args.tailoredResumeDocumentId,
      cover_letter_document_id: args.coverLetterDocumentId,
      applied_via: args.appliedVia || 'website',
      notes: args.notes,
    }
  );
}

// ---------------------------------------------------------------------------
// 6. Quota Limits & Account Analytics
// ---------------------------------------------------------------------------

export interface UsageLimits {
  plan: 'free' | 'pro';
  trialActive: boolean;
  resumeGenerationsRemaining: number;
  coverLetterGenerationsRemaining: number;
  dailyCapResume: number;
  dailyCapCoverLetter: number;
}

export async function getUsageLimits(): Promise<UsageLimits> {
  return callEdgeFunction<UsageLimits>('usage-limits', {}, 'GET');
}

// ---------------------------------------------------------------------------
// 7. Saved Jobs & Applications (PostgREST CRUD)
// ---------------------------------------------------------------------------

export async function getSavedJobs() {
  const user = await getCurrentUser();
  if (!user) return [];

  const { data, error } = await supabase
    .from('saved_jobs')
    .select('*, jobs(*, companies(*))')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false });

  if (error) throw new ApiError(error.message, error.code, 400);
  return data || [];
}

export async function saveJob(jobId: string) {
  const user = await getCurrentUser();
  if (!user) throw new ApiError('Not authenticated', 'unauthorized', 401);

  const { data, error } = await supabase
    .from('saved_jobs')
    .insert({ user_id: user.id, job_id: jobId })
    .select()
    .single();

  if (error && error.code !== '23505') {
    // 23505 = unique constraint (already saved)
    throw new ApiError(error.message, error.code, 400);
  }
  return data;
}

export async function removeSavedJob(jobId: string) {
  const user = await getCurrentUser();
  if (!user) throw new ApiError('Not authenticated', 'unauthorized', 401);

  const { error } = await supabase
    .from('saved_jobs')
    .delete()
    .eq('user_id', user.id)
    .eq('job_id', jobId);

  if (error) throw new ApiError(error.message, error.code, 400);
  return true;
}

export async function getUserApplications() {
  const user = await getCurrentUser();
  if (!user) return [];

  const { data, error } = await supabase
    .from('applications')
    .select('*, jobs(*, companies(*))')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false });

  if (error) throw new ApiError(error.message, error.code, 400);
  return data || [];
}

// ---------------------------------------------------------------------------
// 8. Alerts & Feedback
// ---------------------------------------------------------------------------

export async function getUserAlerts() {
  const user = await getCurrentUser();
  if (!user) return [];

  const { data, error } = await supabase
    .from('alerts')
    .select('*')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false });

  if (error) throw new ApiError(error.message, error.code, 400);
  return data || [];
}

export async function createAlert(alertData: {
  name: string;
  keywords?: string[];
  locations?: string[];
  minConfidence?: number;
  channels?: string[];
}) {
  const user = await getCurrentUser();
  if (!user) throw new ApiError('Not authenticated', 'unauthorized', 401);

  const { data, error } = await supabase
    .from('alerts')
    .insert({
      user_id: user.id,
      name: alertData.name,
      keywords: alertData.keywords || [],
      locations: alertData.locations || [],
      min_confidence: alertData.minConfidence || 60,
      channels: alertData.channels || ['email'],
      is_active: true,
    })
    .select()
    .single();

  if (error) throw new ApiError(error.message, error.code, 400);
  return data;
}

export async function submitFeedback(feedback: {
  category: string;
  message: string;
  rating?: number;
}) {
  return callEdgeFunction('feedback', feedback);
}
