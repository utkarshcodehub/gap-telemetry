-- Market labelling: a demand percentage must never silently span geographies.
--
-- Why this exists. The project's demand numbers are consumed by Indian
-- students, so they have to describe the Indian market. We also hold a large
-- US corpus (Kaggle arshkon/linkedin-job-postings, 123,849 rows) which is
-- measured at ZERO India postings -- see backend/data/README.md. That corpus is
-- deliberately NOT ingested; it is read from disk by experiment scripts only.
--
-- This migration makes that separation structural rather than a convention:
-- get_demand() and get_role_counts() filter on `market`, so even if US rows
-- were ingested later they could not pollute an India demand figure.

alter table public.postings
    add column if not exists market text not null default 'IN';

comment on column public.postings.market is
    'ISO-3166-1 alpha-2 market this posting describes. Demand is never '
    'aggregated across markets; get_demand() filters on it.';

alter table public.postings
    add constraint postings_market_check check (market in ('IN', 'US'));

create index if not exists idx_postings_market_role
    on public.postings(market, role_query);

-- The RPCs gain a p_market parameter defaulting to 'IN'.
--
-- NOTE: these must be DROPped, not just replaced. Adding a parameter changes
-- the signature, so `create or replace` would leave the old single-argument
-- function in place as an overload, and PostgREST would then fail with an
-- ambiguous-function error on every .rpc() call.

drop function if exists public.get_demand(text);

create or replace function public.get_demand(
    p_role_query text default null,
    p_market     text default 'IN'
)
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
        where p.market = p_market
          and (p_role_query is null or p.role_query = p_role_query)
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
    where p.market = p_market
      and (p_role_query is null or p.role_query = p_role_query)
    group by s.id
    order by postings_count desc;
$$;

drop function if exists public.get_role_counts();

create or replace function public.get_role_counts(p_market text default 'IN')
returns table (role_query text, postings bigint)
language sql
stable
as $$
    select role_query, count(*) as postings
    from public.postings
    where market = p_market
    group by role_query
    order by postings desc;
$$;
