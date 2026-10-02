# Market data provenance

Everything else in `backend/data/` is gitignored — these corpora are large and
redistributable only under their own licences, so they are **downloaded, not
committed**. This file is the exception, and it exists so any number in the
report or paper can be traced back to a byte-identical source.

Both archives come from Kaggle's public API. With `~/.kaggle/kaggle.json` in
place:

```bash
cd backend && mkdir -p data/raw/naukri data/raw/linkedin
curl -sSL --fail -u "$KAGGLE_USER:$KAGGLE_KEY" \
  -o data/raw/naukri/naukri-job-listing-dataset.zip \
  "https://www.kaggle.com/api/v1/datasets/download/promptcloud/naukri-job-listing-dataset"
curl -sSL --fail -u "$KAGGLE_USER:$KAGGLE_KEY" \
  -o data/raw/linkedin/linkedin-job-postings.zip \
  "https://www.kaggle.com/api/v1/datasets/download/arshkon/linkedin-job-postings"
```

Verify with `sha256sum` against the checksums below before trusting any result.

---

## 1. Naukri CC0 — the India demand corpus *(ingested into Postgres)*

| | |
|---|---|
| Kaggle slug | `promptcloud/naukri-job-listing-dataset` |
| Version | v1, last updated 2021-07-09 |
| **Licence** | **CC0 1.0 (public domain)** — no attribution obligation, no share-alike |
| Archive | `data/raw/naukri/naukri-job-listing-dataset.zip` |
| SHA-256 | `f74dc34617da91c874c454edddb9131ec185ca786a0cc4a5de259e37f0c73381` |
| Bytes | 7,993,926 |
| Member | `marketing_sample_for_naukri_com-naukri_com_job_data__20201001_20201231__5k_data.ldjson` (38,743,252 B) |
| Rows | 5,000 |
| Date range | **2020-10-01 to 2020-12-31** |
| Geography | India |
| Full JD text | ✅ `job_description` — median 1,376 chars, mean 1,695, max 10,658 |

**Known limitations, stated so they're not discovered later:**

- **It is a 5,000-row sample.** The full 24,641-record set exists only off-Kaggle
  (PromptCloud DataStock) and has not been obtained.
- **It is from Q4 2020** — pre-LLM-era. No posting here mentions RAG, LangChain
  or vector databases, because that market did not exist yet.
- **Only ~1,900 rows are tech at all.** `category` is Naukri's *functional-area*
  taxonomy (73 values) and is mostly non-technical: `Voice` 306, `Retail Sales`
  287, `Accounts`, `HR/Recruitment`, `Medical Professional`, `Teachers`.
- **`country` is dirty**: `'110025 India'`, `'MYSURU Mysore KA 570001 India.'`,
  bare pincodes, `'-'`, and 21 rows of `'USA'`. The loader filters on the
  substring `india` and drops everything else rather than assuming.
- **790 of 5,000 rows survive ingestion.** 271 non-India, 3,939 with no
  determinable role. Only `backend developer` (270) clears the 150-posting
  floor; the other seven canonical roles are under-sampled. The role vocabulary
  is therefore **provisional** until live JSearch volume arrives.

Ingested by `scraper/naukri_cc0_ingest.py` as `source='naukri-cc0-2020q4'`,
`market='IN'`.

---

## 2. LinkedIn 2023–24 — the scale corpus *(NOT ingested — disk only)*

> ### ⚠️ This corpus contains **ZERO India postings**. It must never be used to
> ### describe Indian market demand.

| | |
|---|---|
| Kaggle slug | `arshkon/linkedin-job-postings` |
| Version | v13, created 2024-08-19 |
| **Licence** | **CC BY-SA 4.0** — attribution **and share-alike** |
| Archive | `data/raw/linkedin/linkedin-job-postings.zip` |
| SHA-256 | `4890ecccfdbd6b7ec0e57af6012cae2e960ba74c10702f5957be365469acc7a4` |
| Bytes | 166,472,808 (expands to ~556 MB, 11 CSVs) |
| Main file | `postings.csv`, 516,843,769 B |
| **Rows** | **123,849** (the dataset page claims only "124,000+") |
| Date range | ~2023-09 to 2024-08 |
| Full JD text | ✅ `description`, ~4 KB/row |

### The India measurement

Measured directly over all 123,849 rows, two independent ways:

| Check | Result |
|---|---|
| Distinct `location` strings | 8,526 |
| Literal `India` / unambiguous Indian city | **3 — all false positives** |
| Indian **state** names (`Karnataka`, `Maharashtra`, `Tamil Nadu`, …) | **0 of 8,526** |
| Rows with a US state suffix (`, CA`) | 105,099 — **84.9%** |
| Literal `United States` | 12,695 |
| Entire non-US presence | **35 rows** (Canada 9, China 8, Germany 7, Brazil 3, Mexico 3, Philippines 2, Poland 2, Netherlands 1, South Africa 1) |

The three "India" hits were `Madras, OR` (×2 — Oregon) and `India Hook, SC`
(South Carolina). **The true India count is zero.**

A naive city-name match would have reported ~0.29% India. Those 358 rows were
all `Salem, OR` / `Salem, NH` / `Winston-Salem, NC` / `Delhi, NY` — American
places sharing a name with Indian cities. Any future geography check on this
corpus must keep ambiguous names in a separate bucket.

**Note there is no country column on postings.** The only `country` field in the
archive is on `companies.csv` and holds the **company headquarters**, not the
job location — using it as a proxy would mark a US-headquartered multinational's
Bangalore vacancy as American.

### What it is for

Extraction and taxonomy experiments (plan experiment **E3**), where volume and
rich JD text matter and geography does not, plus a US-vs-India demand
comparison. Read from disk by experiment scripts; **never ingested into
Postgres**, both because of the free tier's 500 MB ceiling (123,849 × ~4 KB
≈ 496 MB of description text alone) and so it cannot contaminate an India
demand figure. Migration `0003` enforces that structurally via
`postings.market`.

**Share-alike caution:** CC BY-SA binds redistribution of the dataset or a
derivative dataset. Publishing aggregate statistics with attribution is fine;
republishing the corpus, or a processed version of it, is not — so experiment
outputs committed to this repo must be **summary tables, never row-level
exports**.

---

## 3. JSearch — live India feed *(LIVE)*

| | |
|---|---|
| Provider | OpenWeb Ninja (`openwebninja.com`), subscribed **directly**, not via RapidAPI |
| Terms | Reviewed 2026-10-02, document dated 2026-09-14; archived in `docs/legal/` |
| Storing results in our DB | ✅ **Explicitly permitted** |
| Ingested as | `source='jsearch'`, `market='IN'` |
| First load | **583 postings**, 2026-10-02, for 16 requests |

### Measured API behaviour (do not trust the docs over these)

| | |
|---|---|
| Results per call | ~9.4 per page; `num_pages=5` → ~47 |
| **Request cost** | **`ceil(num_pages / 5)`** — pages are NOT free |
| Results per *request* | **flat at ~47** regardless of `num_pages`, so deeper pages buy nothing |
| `job_description` | full text, median ~2,300–3,000 chars, no truncation |
| `country=in` | reliable; `job_country` is `IN` or blank, never a wrong country |
| Quota headers | **none** — hence `core/market/quota.py` |
| Allowance | 200 per billing period, resetting on **the 2nd**, not the 1st |

### ⚠️ `external_id` must be `job_uid`, never `job_id`

`job_id` is ~402 characters and decodes to `<job_uid>:<rotating per-request token>`, so the
same posting returns a **different `job_id` on every call**. Keying on it made two identical
queries appear 100% disjoint, and would have re-inserted the entire corpus as new rows on
every run — inflating counts, distorting every demand percentage, and preventing the
already-held early-stop from ever firing. `job_uid` is the stable 24-char Google docid.
Asserted by `tests/test_jsearch_mapping.py`.

### Attribution and limits

The provider's terms grant "a non-exclusive, non-transferable license to use,
reproduce, and commercially exploit such API Data in your own products…
including for resale or redistribution as part of a broader product offering".
The sole carve-out is reselling as "a standalone data or API product" that
"substantially replicates the Services themselves" — which aggregate demand
percentages are not. No attribution is required for API Data, and nothing
prohibits publishing derived aggregates.

Three things to carry forward:

- **Subscribe directly at openwebninja.com, not through RapidAPI**, so the terms
  above govern. RapidAPI's own ToS could not be read (JS-only page) and would
  otherwise stack an unreviewed contract on top.
- **Retention is unaddressed.** No caching or retention limit appears anywhere
  in the terms. That is silence, not permission — though it sits beside an
  affirmative reproduction licence.
- **Upstream rights are pushed onto the consumer.** Content originates from
  Google for Jobs / LinkedIn / Indeed / Glassdoor, and the provider's indemnity
  clause covers third-party IP. Storing full JD text is the exposed part;
  publishing only aggregates is the mitigation. Archive a dated PDF of the terms
  for the report appendix.

---

## 4. Synthetic generator — **no longer a data source**

`scraper/synthetic_generator.py` is retained for **test fixtures only**. Its
skill probabilities (Python 0.92, SQL 0.60, RAG 0.22) were typed by hand, so any
demand percentage derived from it describes a market that does not exist. The
500 synthetic rows it had seeded were deleted from the database on 2026-10-02
when the Naukri corpus was ingested. It reproduces them byte-identically if ever
needed:

```bash
cd backend && python ../scraper/synthetic_generator.py --count 500 --seed 42
```
