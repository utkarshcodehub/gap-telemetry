-- Job-Skill Gap Intelligence — core schema.
--
-- Mirrors the old SQLite schema (core/db/store.py) but native to Postgres,
-- plus real Row-Level Security on saved_analyses instead of hand-rolled
-- WHERE-clause scoping. Market tables (postings/skills/posting_skills) are
-- public read-only data — anyone can SELECT, only the service_role
-- (backend ingest scripts) can write, since RLS default-denies writes for
-- anon/authenticated with no matching policy.

create table if not exists public.postings (
    id          bigint generated always as identity primary key,
    source      text not null,
    external_id text not null,
    title       text not null,
    company     text,
    location    text,
    experience  text,
    salary      text,
    description text not null,
    role_query  text not null,
    scraped_at  timestamptz not null default now(),
    unique (source, external_id)
);

create table if not exists public.skills (
    id        bigint generated always as identity primary key,
    canonical text not null unique,
    category  text not null
);

create table if not exists public.posting_skills (
    posting_id    bigint not null references public.postings(id) on delete cascade,
    skill_id      bigint not null references public.skills(id) on delete cascade,
    mention_count integer not null default 1,
    primary key (posting_id, skill_id)
);

create index if not exists idx_postings_role on public.postings(role_query);
create index if not exists idx_ps_skill on public.posting_skills(skill_id);

-- Personal data: one row per saved gap report, owned by a Supabase Auth user.
create table if not exists public.saved_analyses (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references auth.users(id) on delete cascade,
    role            text not null,
    readiness_score double precision not null,
    report_json     jsonb not null,
    created_at      timestamptz not null default now()
);

create index if not exists idx_saved_analyses_user on public.saved_analyses(user_id);

-- ---------------------------------------------------------------- RLS

alter table public.postings enable row level security;
alter table public.skills enable row level security;
alter table public.posting_skills enable row level security;
alter table public.saved_analyses enable row level security;

create policy "postings are publicly readable"
    on public.postings for select
    using (true);

create policy "skills are publicly readable"
    on public.skills for select
    using (true);

create policy "posting_skills are publicly readable"
    on public.posting_skills for select
    using (true);

-- saved_analyses: a user can only ever see/insert/delete their own rows.
-- This is the real enforcement boundary now (not just an app-level WHERE
-- clause) — Postgres checks it on every query regardless of how it's issued.
create policy "select own analyses"
    on public.saved_analyses for select
    using (auth.uid() = user_id);

create policy "insert own analyses"
    on public.saved_analyses for insert
    with check (auth.uid() = user_id);

create policy "delete own analyses"
    on public.saved_analyses for delete
    using (auth.uid() = user_id);

-- ---------------------------------------------------------------- RPCs
-- PostgREST's query builder can't express GROUP BY / aggregate joins, so
-- the two aggregate reads the app needs (demand-by-skill, postings-by-role)
-- are plain SQL functions called via .rpc(...) instead.

create or replace function public.get_demand(p_role_query text default null)
returns table (
    canonical      text,
    category       text,
    postings_count bigint,
    demand_pct     numeric,
    total_mentions bigint
)
language sql
stable
as $$
    with total as (
        select count(*)::numeric as n
        from public.postings p
        where p_role_query is null or p.role_query = p_role_query
    )
    select
        s.canonical,
        s.category,
        count(distinct ps.posting_id) as postings_count,
        round(count(distinct ps.posting_id) / nullif((select n from total), 0) * 100, 1) as demand_pct,
        sum(ps.mention_count) as total_mentions
    from public.posting_skills ps
    join public.skills   s on s.id = ps.skill_id
    join public.postings p on p.id = ps.posting_id
    where p_role_query is null or p.role_query = p_role_query
    group by s.id
    order by postings_count desc;
$$;

create or replace function public.get_role_counts()
returns table (role_query text, postings bigint)
language sql
stable
as $$
    select role_query, count(*) as postings
    from public.postings
    group by role_query
    order by postings desc;
$$;
