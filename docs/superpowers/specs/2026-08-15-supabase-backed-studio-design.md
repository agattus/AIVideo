# Supabase-Backed S-Studio Design

**Date:** 2026-08-15  
**Status:** Approved (Approach 1 + captivating auth UI)  
**Stack:** Railway API (pipeline) + Supabase (Auth / Postgres / Storage)

## Problem

S-Studio today is effectively single-tenant: jobs live on disk + Redis with no user accounts. Deploying “to Supabase” as a full host is not viable (FFmpeg / long Python jobs). We need a real multi-user product surface while keeping render on Railway.

## Goals

- Magic-link Auth (Supabase)
- Multi-user: each user only sees **their** jobs
- Postgres as system of record for jobs
- Supabase Storage for durable artifacts (stills, audio, final MP4)
- Railway continues to run FastAPI + TTS + image gen + FFmpeg assemble
- **Captivating UI** for login and first authenticated viewport (brand-led, not a generic dashboard chrome)

## Non-goals (v1)

- Google OAuth (follow-up)
- Migrating anonymous legacy jobs into user accounts
- Replacing Celery/FFmpeg with Edge Functions
- Billing / quotas
- Team / shared workspaces

## Architecture

```
Browser (React Studio)
  └─ Supabase Auth (magic link)
  └─ API calls → Railway FastAPI  (Authorization: Bearer <jwt>)
       ├─ verify JWT (Supabase JWKS / JWT secret)
       ├─ Postgres jobs (user_id scoped)
       ├─ local output/ scratch during render
       └─ upload artifacts → Supabase Storage
```

## Data model (Postgres)

### `profiles`
| Column | Type | Notes |
|--------|------|--------|
| `id` | uuid PK | = `auth.users.id` |
| `display_name` | text | optional |
| `created_at` | timestamptz | |

Trigger: on auth signup → insert profile.

### `jobs`
| Column | Type | Notes |
|--------|------|--------|
| `id` | uuid PK | pipeline job_id |
| `user_id` | uuid FK → profiles | RLS owner |
| `status` | text | queued / processing / waiting_for_assets / completed / failed |
| `title` | text | |
| `idea` | text | |
| `format` | text | narrative / dialogue / quizverse |
| `style` | text | |
| `aspect_ratio` | text | |
| `language` | text | |
| `error` | text nullable | |
| `progress_percent` | int | |
| `current_stage` | text | |
| `storage_prefix` | text | e.g. `{user_id}/{job_id}/` |
| `result_video_path` | text nullable | storage object key |
| `thumb_path` | text nullable | |
| `created_at` / `updated_at` | timestamptz | |

### RLS
- `profiles`: select/update own row  
- `jobs`: CRUD where `user_id = auth.uid()`  
- Service role (Railway) bypasses RLS for worker updates

## Storage

Bucket: `job-assets` (private)

Object layout:
```
{user_id}/{job_id}/audio/voiceover.mp3
{user_id}/{job_id}/scenes/scene_00.jpg
{user_id}/{job_id}/video/final.mp4
{user_id}/{job_id}/meta/youtube_metadata.json
…
```

- Studio playback via **signed URLs** (short TTL) from API  
- Railway uses **service role** to upload after Phase 1 / assemble

## API changes (Railway)

Env:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` (optional; browser uses this directly for auth)
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET` (or JWKS URL)

Behavior:
1. Auth middleware on `/api/v1/generate`, `/jobs`, `/jobs/{id}/*`  
2. Unauthenticated → `401`  
3. `POST /generate` creates `jobs` row with `user_id` from JWT  
4. `GET /jobs` lists only current user’s jobs  
5. Workspace/status responses may include signed URLs instead of only `/static/...`  
6. Dev escape hatch: `AUTH_DISABLED=1` for local offline (never in prod)

Keep Redis/Celery as optional worker queue; Postgres is source of truth for library UI.

## Captivating UI (v1)

### Login / magic-link gate
- Full-bleed atmospheric hero (film grain / night-sky still or gradient plane — **not** purple-on-white, not cream-serif terracotta cliché)
- Brand **S-Studio** (or product name) as hero-level signal
- One headline, one short line, one email field + “Send magic link” CTA
- No dashboard cards in the first viewport
- Expressive typography (non-system; avoid Inter/Roboto/Arial)
- Subtle motion: brand fade/rise, CTA pulse or link-sent state transition
- Success state: “Check your email” composition (same visual world)

### Authenticated shell
- Preserve existing Studio workflows (Generate, JobStudio)
- Job library scoped to user
- Sign-out control in chrome (minimal; don’t turn first viewport into a dashboard)

### Frontend libs
- `@supabase/supabase-js` for magic link + session
- Attach `session.access_token` to API `Authorization` header

## Implementation phases

1. **Schema + RLS + bucket** (SQL migrations in repo)  
2. **API auth middleware + job persistence**  
3. **Storage upload + signed URL helpers**  
4. **Captivating login UI + session wiring**  
5. **Docs / Railway + Supabase env checklist**

## Success criteria

- User A cannot list or open User B’s jobs (API + RLS)  
- Magic link sign-in works end-to-end against a Supabase project  
- Completed job video playable via signed URL  
- Login first viewport passes brand test (brand still clear if nav removed)  
- Pipeline still runs on Railway with FFmpeg

## Follow-ups

- Google OAuth  
- Legacy job import  
- Quotas / billing  
- Realtime job progress via Supabase Realtime
