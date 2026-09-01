-- Migration 2026090113: resumes.section_order
-- Adds section_order JSONB column to public.resumes to capture the candidate's original resume structure.

ALTER TABLE public.resumes
ADD COLUMN IF NOT EXISTS section_order JSONB DEFAULT '[]'::jsonb;
