# Supabase setup (S-Studio)

1. Create a project at [supabase.com](https://supabase.com).
2. **Authentication → Providers**: enable Email; turn on **Magic link**.
3. **SQL → New query**: paste and run `migrations/20260815_init_studio.sql`.
4. **Project Settings → API**: copy
   - Project URL → `SUPABASE_URL` / `VITE_SUPABASE_URL`
   - `anon` `public` key → `VITE_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (Railway only — never ship to browser)
5. **Project Settings → API → JWT Secret** → `SUPABASE_JWT_SECRET`
6. **Authentication → URL configuration**: add your Studio origins (e.g. `http://127.0.0.1:5173`, Railway URL) to Redirect URLs.
7. Set the same vars on Railway. Leave unset locally to keep `AUTH_DISABLED` behavior (open studio).

Pipeline still runs on Railway; Supabase holds Auth, job rows, and durable files.
