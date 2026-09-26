# Supabase-Backed S-Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-user S-Studio with Supabase magic-link Auth, Postgres jobs, Storage artifacts, captivating login UI; Railway keeps the render pipeline.

**Architecture:** Browser authenticates via Supabase JS; API verifies JWTs and scopes jobs to `user_id`; workers use service role to upsert jobs and upload to Storage; local `output/` remains scratch.

**Tech Stack:** Supabase Auth/Postgres/Storage, FastAPI, React/Vite, `@supabase/supabase-js`, `PyJWT`/`httpx` or `supabase-py`

## Global Constraints

- Magic link auth (v1); no Google OAuth yet
- Multi-user: each user only sees their jobs
- Railway hosts API/FFmpeg; Supabase is Auth + DB + Storage
- Captivating brand-first login (S-Studio); avoid purple-on-white / cream-terracotta clichés
- `AUTH_DISABLED=1` local escape hatch only

---

### Task 1: SQL migrations

**Files:**
- Create: `supabase/migrations/20260815_init_studio.sql`
- Create: `supabase/README.md` (apply checklist)

- [x] profiles + jobs tables, RLS, storage bucket policies
- [x] Document how to run in Supabase SQL editor

### Task 2: Backend auth + Supabase client

**Files:**
- Create: `src/youtube_pipeline/api/auth.py`
- Create: `src/youtube_pipeline/api/supabase_client.py`
- Modify: `config/settings.py`, `.env.example`
- Test: `tests/test_supabase_auth.py`

- [x] JWT verify dependency + AUTH_DISABLED
- [x] Service-role client helper

### Task 3: Job persistence + list/generate scoping

**Files:**
- Create: `src/youtube_pipeline/api/supabase_jobs.py`
- Modify: `job_store.py`, `main.py` generate/list/status
- Test: `tests/test_supabase_jobs.py`

- [x] init/upsert/list by user_id
- [x] Wire generate + list endpoints

### Task 4: Storage helpers

**Files:**
- Create: `src/youtube_pipeline/api/supabase_storage.py`
- Modify: publish/assemble hooks (minimal: final video + thumb)
- Test: mocked upload/sign

- [x] Upload final MP4 + thumb after assemble; signed URLs on library list

### Task 5: Captivating login + API session

**Files:**
- Create: `frontend/src/lib/supabase.ts`, `AuthGate.tsx`, `LoginPage.tsx`
- Modify: `App.tsx`, `AppShell.tsx`, `client.ts`, `global.css`
- Add deps: `@supabase/supabase-js`

- [x] Magic link page (noir atmospheric)
- [x] Bearer token on API calls
- [x] Sign out
