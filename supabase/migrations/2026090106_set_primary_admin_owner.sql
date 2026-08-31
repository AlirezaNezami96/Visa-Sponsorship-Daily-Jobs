-- Migration: 2026090106_set_primary_admin_owner.sql
-- Description: Set primary owner email to alireza.nezami75@gmail.com and deactivate any other accounts.

INSERT INTO public.admin_users (email, role, active)
VALUES ('alireza.nezami75@gmail.com', 'owner', TRUE)
ON CONFLICT (email) DO UPDATE SET role = 'owner', active = TRUE;

-- Deactivate placeholder accounts if any
UPDATE public.admin_users
SET active = FALSE
WHERE email != 'alireza.nezami75@gmail.com';
