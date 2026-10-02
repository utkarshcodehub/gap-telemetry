# Manifest selection & channel-map coverage — measurement, 2026-10-02

Input for Dataset A tuning. Measured on one real profile (the project author,
23 non-fork repos), so treat it as a strong hint rather than a result — n=1.

## What was changed

Manifest selection was **ranked**, not raised blindly:

- root-level manifests before nested ones (a repo's real dependency set lives at
  the top; a nested one is usually an example or sub-package)
- then by `MANIFEST_SIGNAL_RANK` — `requirements.txt` and `package.json` declare
  dozens of libraries each, so they resolve far more skills per request than a
  `Gemfile` typically does
- then by depth

The per-repo cap became **budget-derived** rather than fixed:
`_manifest_allowance()` reserves one tree plus one contributors call for every
remaining repo and divides what is left. A large profile therefore degrades
gracefully instead of breaching NFR-2.

## Result

| | Before | After |
|---|---|---|
| Requests for 23 repos | 81 | **83** (NFR-2 cap: 150) |
| Manifest files fetched | — | 36 (~1.6 per repo) |
| VERIFIED skills | 16 | 16 |

**The manifest cap was never the binding constraint.** Most repos declare only
one or two manifests, so a higher ceiling fetched almost nothing extra. The
earlier hypothesis — that `langchain` and `openai` were sitting in files we never
opened — was wrong, and the measurement is what disproved it.

## The actual limiting factor: channel-map coverage

Across all 36 fetched manifests, **93 distinct packages** were declared.

| | Count |
|---|---|
| Recognised by the channel map | 20 |
| Unrecognised | 73 |

Most of the 73 are **transitive dependencies** (`anyio`, `h11`, `idna`,
`typing_extensions`, `pydantic_core`, `starlette`) — noise that should never map
to a skill. But the frequency ranking exposed one real gap:

| Package | Manifests | Consequence |
|---|---|---|
| **`groq`** | **12** | `Large Language Models` read `UNVERIFIABLE` on an LLM-heavy profile |
| `langchain`, `openai`, `anthropic`, `transformers` | **0** | the aggregators this project assumed were ubiquitous are simply not used here |

The candidate calls a model provider's API directly. That is the common pattern,
not the exception, and the map only listed aggregators plus two providers.

**Fix:** `Large Language Models` now covers the provider SDKs —
`groq`, `google-generativeai`, `cohere`, `mistralai`, `together`, `replicate`
alongside the existing entries. `Large Language Models` moved
**`UNVERIFIABLE` → `VERIFIED` (E3, 12 repos)**; VERIFIED went 16 → **17**.

## For Dataset A tuning

1. **Measure channel-map recall before touching thresholds.** On this profile the
   map, not the collection strategy, decided the outcome. Tuning confidence
   constants against a map with holes would fit the constants to the holes.
2. **Rank unrecognised packages by frequency across the dataset.** It took one
   ranked list to find `groq`; the same method over Dataset A will surface the
   rest cheaply.
3. **Do not map transitive dependencies.** `pydantic_core` appearing in a
   requirements file says nothing about a candidate; only direct, intentional
   dependencies are evidence.
4. **Known gaps outside the current taxonomy**, for Member C rather than this
   map: `streamlit` (8 manifests) and `vite` (12) are real, commonly-claimed
   skills with no canonical entry at all, so they cannot be verified however good
   the channel map gets.
