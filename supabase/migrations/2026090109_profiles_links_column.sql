-- Ensure the profiles table stores structured profile links
ALTER TABLE public.profiles
ADD COLUMN IF NOT EXISTS links JSONB DEFAULT '[]'::jsonb;
