-- S-Studio: profiles, jobs, storage (apply in Supabase SQL editor)
-- Spec: docs/superpowers/specs/2026-08-15-supabase-backed-studio-design.md

create extension if not exists "pgcrypto";

-- Profiles (1:1 with auth.users)
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles_select_own"
  on public.profiles for select
  using (auth.uid() = id);

create policy "profiles_update_own"
  on public.profiles for update
  using (auth.uid() = id);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Jobs
create table if not exists public.jobs (
  id uuid primary key,
  user_id uuid not null references public.profiles (id) on delete cascade,
  status text not null default 'queued',
  title text,
  idea text,
  format text,
  style text,
  aspect_ratio text,
  language text default 'en',
  error text,
  progress_percent integer not null default 0,
  current_stage text,
  storage_prefix text,
  result_video_path text,
  thumb_path text,
  run_dir text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists jobs_user_id_updated_at_idx
  on public.jobs (user_id, updated_at desc);

alter table public.jobs enable row level security;

create policy "jobs_select_own"
  on public.jobs for select
  using (auth.uid() = user_id);

create policy "jobs_insert_own"
  on public.jobs for insert
  with check (auth.uid() = user_id);

create policy "jobs_update_own"
  on public.jobs for update
  using (auth.uid() = user_id);

create policy "jobs_delete_own"
  on public.jobs for delete
  using (auth.uid() = user_id);

-- Private storage bucket for artifacts
insert into storage.buckets (id, name, public)
values ('job-assets', 'job-assets', false)
on conflict (id) do nothing;

-- Users can read objects under their own prefix: {user_id}/...
create policy "job_assets_select_own"
  on storage.objects for select
  using (
    bucket_id = 'job-assets'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "job_assets_insert_own"
  on storage.objects for insert
  with check (
    bucket_id = 'job-assets'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "job_assets_update_own"
  on storage.objects for update
  using (
    bucket_id = 'job-assets'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "job_assets_delete_own"
  on storage.objects for delete
  using (
    bucket_id = 'job-assets'
    and auth.uid()::text = (storage.foldername(name))[1]
  );
