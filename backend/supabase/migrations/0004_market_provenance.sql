-- Per-source composition of the market corpus, for honest attribution in the UI.
--
-- The UI says things like "Strengths the market is paying for". It must therefore
-- be able to say WHICH market and from WHAT data, because the corpus is mixed:
-- an archival Naukri sample (Q4 2020) alongside a live feed (current). Without
-- this, a reader cannot tell whether a demand percentage describes today's market
-- or one from five years ago, and the two differ substantially -- the 2020 sample
-- contains no LLM, RAG or MLOps postings at all.
--
-- PostgREST cannot express GROUP BY, which is why this is an RPC like get_demand
-- and get_role_counts rather than a query built in the client.
--
-- Note: `scraped_at` is when WE ingested, not when the posting was published, so
-- it is deliberately NOT reported as a vintage. The source slug carries that
-- (naukri-cc0-2020q4), and the human label lives in core/market/sources.py.

create or replace function public.get_market_provenance(p_market text default 'IN')
returns table (source text, postings bigint)
language sql
stable
as $$
    select source, count(*) as postings
    from public.postings
    where market = p_market
    group by source
    order by postings desc;
$$;
