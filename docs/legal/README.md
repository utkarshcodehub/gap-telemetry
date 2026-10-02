# Archived third-party terms

Dated captures of the terms the project relies on, kept because vendors revise
them without notice — OpenWeb Ninja's own terms state that revisions bind you by
continued use and that you "waive any right to receive specific notice of each
such change". If a clause this project depends on changes later, these files are
the evidence of what was in force when the decision was made.

Verify any file with `sha256sum` before citing it.

---

## `openwebninja-terms-2026-10-02.*`

| | |
|---|---|
| Source | <https://www.openwebninja.com/terms> |
| Captured | **2026-10-02** |
| Document's own date | **"Last updated Sep 14, 2026"** |
| Operator | Whats Next Labs LLC, Sunnyvale CA |
| `...-2026-10-02.html` | 180,996 B · `sha256 cffd66e9c2e5b87930ef0f2d80e8458680c94bb9a83eeabd302aa337558d3314` |
| `...-2026-10-02.txt` | 38,058 B · `sha256 7f6acbfd67e959d4f79734f8ed6bde90d30401404c10ec39868a187b7683ceca` |

The `.html` is the document as served; the `.txt` is a tag-stripped rendering of
that same file, for reading and diffing. Both are checked in because the HTML is
authoritative and the text is legible.

**Why this document matters.** It is what permits the project to store JSearch
results in its own database. The governing clause:

> "a non-exclusive, non-transferable license to use, reproduce, and commercially
> exploit such API Data in your own products … including for resale or
> redistribution as part of a broader product offering"

conditioned only on not reselling API Data "as a standalone data or API product"
that "substantially replicates the Services themselves". Aggregate skill-demand
percentages are neither. No attribution is required for API Data, and nothing
prohibits publishing derived aggregates. Full reasoning in
`backend/data/README.md` §3.

**On the format.** The README asked for a PDF. This is an HTML+text capture
instead, for a specific reason: the page is client-rendered and would not reach a
stable state in a headless browser, so any PDF produced here would be a
reconstruction rather than the served document. The `.html` above *is* the served
document, byte-for-byte, which is a stronger artifact. **If the university wants
a PDF specifically for the appendix, open the URL and use the browser's
Print → Save as PDF** — that is the one step a human has to do, and it should be
dated the same way.

**Not legal advice.** The project's own institution may require separate
data-governance or ethics sign-off for storing third-party job content,
independent of what the vendor permits.
