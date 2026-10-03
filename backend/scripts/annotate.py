"""
The Dataset A annotation tool.

    cd backend
    python scripts/annotate.py --task dry_run --annotator utkarsh

One claim per screen. Keys: d (demonstrated), n (not demonstrated),
u (undeterminable), s skip, b back, / search the file trees, ? definitions,
q save and quit. Progress saves after every answer, so quitting costs nothing and
re-running resumes.

Protocol: docs/ANNOTATION_PROTOCOL.md. Read it before using this.

WHAT THIS TOOL DELIBERATELY DOES NOT SHOW. The engine's verdict, tier or
confidence, and no list of "relevant" files chosen by the channel map. Ground
truth anchored to the engine's own output would make experiment E1 a comparison of
the engine with itself. The artifacts shown are a map-independent digest -- root
files, directories, extensions, declared packages, language, recency, authorship --
and `/pattern` searches the full file tree, so an annotator can look for anything
they think matters rather than only what we thought to surface.

Labels go to data/annotations/<task>/<annotator>.jsonl, which is gitignored.
Annotators work independently; see the protocol's rule 1 and why it exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "annotations"

LABELS = {
    "d": "demonstrated",
    "n": "not demonstrated",
    "u": "undeterminable",
}

DEFINITIONS = """
  d  demonstrated       An artifact shows the skill in use: a file that only
                        exists because of it (Dockerfile, *.tf, *.ipynb), a
                        declared dependency, or source files in the language.
                        A README mention is NEVER enough on its own -- that is
                        the candidate writing a claim in a different box.

  n  not demonstrated   TWO conditions, both required: the skill is absent, AND
                        you would have expected to see it here if they used it.
                        23 repos with no Dockerfile means `n` for someone who
                        publishes Terraform, and `u` for someone whose public
                        work is coursework. If both conditions are not met, the
                        answer is `u`. A note is required for `n`.

  u  undeterminable     No artifact could show it ("Communication", "System
                        Design") -- a category, not a failure. Or the public
                        surface is too thin. Or collection was partial. Or you
                        genuinely cannot tell. Always available, never a cop-out.
"""


def load_task(name: str) -> tuple[list[dict], dict]:
    d = OUT_ROOT / name
    items_path, profiles_path = d / "items.jsonl", d / "profiles.json"
    if not items_path.exists():
        sys.exit(f"no task at {d}. Build one with scripts/build_annotation_task.py")
    items = [json.loads(l) for l in items_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    return items, profiles


def load_done(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["id"]] = row
    return out


def append(path: Path, row: dict) -> None:
    """Append-only, flushed per answer: quitting mid-task must never lose work."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
        f.flush()


def render_profile(prof: dict) -> str:
    """The artifacts, as plainly as possible."""
    lines = [
        f"  profile {prof['profile']}   {prof['repos_in_scope']} repos in scope"
        f"   collection: {prof['collection'].upper()}",
    ]
    if prof["collection"] == "partial":
        lines.append("  ** collection was INCOMPLETE -- absence here is not evidence **")
    for r in prof["repos"]:
        share = ("?" if r["authorship_share"] is None
                 else f"{r['authorship_share'] * 100:.0f}% of commits")
        age = ("?" if r["pushed_months_ago"] is None
               else f"{r['pushed_months_ago']:.0f} months ago")
        lines.append("")
        lines.append(f"  - {r['repo']}   [{r['primary_language'] or 'no language'}]"
                     f"   pushed {age}   {share}   {r['files_total']} files")
        if r["root_files"]:
            extra = (f" (+{r['root_files_truncated']} more)"
                     if r["root_files_truncated"] else "")
            lines.append(f"      root:    {', '.join(r['root_files'])}{extra}")
        if r["directories"]:
            lines.append(f"      dirs:    {', '.join(r['directories'])}")
        if r["extensions"]:
            exts = "  ".join(f"{k} x{v}" for k, v in r["extensions"].items())
            lines.append(f"      files:   {exts}")
        if r["packages"]:
            lines.append(f"      declared: {', '.join(r['packages'])}")
    return "\n".join(lines)


def search(prof: dict, pattern: str) -> str:
    """Grep the full trees. Case-insensitive substring, which is what an annotator
    actually wants and needs no explaining."""
    pat = pattern.lower().strip()
    if not pat:
        return "  (empty pattern)"
    out = []
    for r in prof["repos"]:
        hits = [p for p in r["tree"] if pat in p.lower()]
        if hits:
            shown = hits[:12]
            more = f"  (+{len(hits) - len(shown)} more)" if len(hits) > len(shown) else ""
            out.append(f"  {r['repo']}: {', '.join(shown)}{more}")
    return "\n".join(out) if out else f"  no path contains '{pattern}' in any repo"


def render_item(item: dict, index: int, total: int) -> str:
    return (
        f"\n{'=' * 78}\n"
        f"  claim {index} of {total}\n\n"
        f"  Does this person's public work demonstrate:  {item['skill'].upper()}\n"
        f"  (claimed for the role '{item['role']}', where it appears in "
        f"{item['role_demand_pct']:.0f}% of postings)\n"
        f"{'=' * 78}"
    )


def run(task: str, annotator: str) -> int:
    items, profiles = load_task(task)
    out_path = OUT_ROOT / task / f"{annotator}.jsonl"
    done = load_done(out_path)

    print(__doc__.split("Protocol:")[0].rstrip())
    print(f"task {task}   annotator {annotator}   "
          f"{len(done)} of {len(items)} already labelled")

    i = 0
    while i < len(items):
        item = items[i]
        if item["id"] in done:
            i += 1
            continue
        prof = profiles[item["profile"]]
        print(render_item(item, i + 1, len(items)))
        print(render_profile(prof))
        print()

        while True:
            try:
                raw = input("  d / n / u   (s skip, b back, /search, ? help, q quit) > ")
            except EOFError:
                print("\n  no input available; stopping.")
                return 1
            key = raw.strip()
            if key == "?":
                print(DEFINITIONS)
                continue
            if key.startswith("/"):
                print(search(prof, key[1:]))
                continue
            if key == "q":
                print(f"\n  saved {len(done)} labels to {out_path}")
                return 0
            if key == "s":
                i += 1
                break
            if key == "b":
                i = max(0, i - 1)
                # Re-answering means replacing: the file is append-only, so the
                # LAST line for an id wins and load_done() keeps it.
                done.pop(items[i]["id"], None)
                break
            if key in LABELS:
                note = ""
                if key == "n":
                    # Required, not optional. `n` is the only label that can read
                    # as an accusation, so it carries its reasoning.
                    while not note.strip():
                        note = input("  what did you look for, and where? > ")
                else:
                    note = input("  note (optional) > ")
                row = {
                    "id": item["id"],
                    "profile": item["profile"],
                    "skill": item["skill"],
                    "label": LABELS[key],
                    "note": note.strip(),
                    "annotator": annotator,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                append(out_path, row)
                done[item["id"]] = row
                i += 1
                break
            print("  unrecognised. d, n, u, s, b, /pattern, ? or q.")

    print(f"\n  done: {len(done)} of {len(items)} labelled -> {out_path}")
    print("  Send this file to the lane A owner. Do not compare it with anyone "
          "else's first -- see protocol rule 1.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="task name under data/annotations/")
    ap.add_argument("--annotator", required=True, help="your name, lowercase")
    args = ap.parse_args()
    sys.exit(run(args.task, args.annotator.strip().lower()))


if __name__ == "__main__":
    main()
