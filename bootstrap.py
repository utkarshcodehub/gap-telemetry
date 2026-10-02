#!/usr/bin/env python3
"""
One-command setup and health check for the whole project.

    python bootstrap.py           # set up what it can, report what it cannot
    python bootstrap.py --check    # verify only; change nothing

Written because the setup used to have steps that were easy to skip and failed
far away from the cause. Three real examples, all of which this script now
catches by name:

  - The SQL migrations were never mentioned in the run instructions. Skip them
    and every route fails with an opaque 500 against a schema-less database.
  - backend/.env and frontend/.env are separate files that must point at the same
    Supabase project. The frontend does NOT fail loudly when its values are
    missing -- it logs a console warning, then login fails with an unhelpful
    error.
  - The README told you to download a spaCy model the code never loads.

Stdlib only, so it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WINDOWS = platform.system() == "Windows"
VENV = BACKEND / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")

MIN_PY = (3, 11)

OK, WARN, FAIL, SKIP = "  ok ", " warn", " FAIL", " skip"
_problems: list[str] = []
_notes: list[str] = []


def say(status: str, what: str, detail: str = "") -> None:
    print(f"[{status}] {what}" + (f"\n         {detail}" if detail else ""))
    if status == FAIL:
        _problems.append(f"{what}: {detail}" if detail else what)
    elif status == WARN:
        _notes.append(f"{what}: {detail}" if detail else what)


def run(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


# --------------------------------------------------------------------- steps

def step_python() -> None:
    v = sys.version_info
    if v[:2] >= MIN_PY:
        say(OK, f"python {v.major}.{v.minor}.{v.micro}")
    else:
        say(FAIL, f"python {v.major}.{v.minor} is too old",
            f"needs >= {MIN_PY[0]}.{MIN_PY[1]}")


def step_backend_venv(check: bool) -> None:
    if VENV_PY.exists():
        say(OK, "backend venv")
        return
    if check:
        say(FAIL, "backend venv missing", "run: python bootstrap.py")
        return
    code, out = run([sys.executable, "-m", "venv", "venv"], BACKEND)
    say(OK if code == 0 else FAIL, "backend venv created",
        "" if code == 0 else out[-400:])


def step_backend_deps(check: bool) -> None:
    if not VENV_PY.exists():
        say(SKIP, "backend dependencies", "no venv yet")
        return
    code, _ = run([str(VENV_PY), "-c", "import fastapi, supabase, spacy, pypdf"],
                  BACKEND, timeout=180)
    if code == 0:
        say(OK, "backend dependencies")
        return
    if check:
        say(FAIL, "backend dependencies missing", "run: python bootstrap.py")
        return
    print("         installing backend requirements (this takes a minute)...")
    code, out = run([str(VENV_PY), "-m", "pip", "install", "-q", "-r",
                     "requirements.txt"], BACKEND)
    say(OK if code == 0 else FAIL, "backend dependencies installed",
        "" if code == 0 else out[-500:])
    # NOTE: no spaCy model download. extraction uses spacy.blank("en") on
    # purpose -- see "Key design decisions" #1 in the README.


def _env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def step_env_files(check: bool) -> tuple[dict, dict]:
    be, fe = BACKEND / ".env", FRONTEND / ".env"
    for path in (be, fe):
        if path.exists():
            continue
        example = path.parent / ".env.example"
        if check:
            say(FAIL, f"{path.relative_to(ROOT)} missing",
                f"copy {example.relative_to(ROOT)} and fill it in")
            continue
        if example.exists():
            shutil.copyfile(example, path)
            say(WARN, f"created {path.relative_to(ROOT)} from .env.example",
                "it still needs your real values - see README 'Setting up Supabase Auth'")
        else:
            say(FAIL, f"{path.relative_to(ROOT)} missing and no .env.example")

    bev, fev = _env_values(be), _env_values(fe)

    for key, where in [("SUPABASE_URL", bev), ("SUPABASE_ANON_KEY", bev)]:
        say(OK if where.get(key) else FAIL, f"backend/.env {key}",
            "" if where.get(key) else "not set")
    if not bev.get("SUPABASE_SERVICE_ROLE_KEY"):
        say(WARN, "backend/.env SUPABASE_SERVICE_ROLE_KEY not set",
            "reads work; seeding market data does not")
    for key in ("VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY"):
        say(OK if fev.get(key) else FAIL, f"frontend/.env {key}",
            "" if fev.get(key) else "not set - login will fail with an unhelpful error, "
                                    "NOT a startup failure")

    # The trap worth catching explicitly.
    if bev.get("SUPABASE_URL") and fev.get("VITE_SUPABASE_URL"):
        if bev["SUPABASE_URL"].rstrip("/") != fev["VITE_SUPABASE_URL"].rstrip("/"):
            say(FAIL, "backend and frontend point at DIFFERENT Supabase projects",
                f"{bev['SUPABASE_URL']} vs {fev['VITE_SUPABASE_URL']}")
        else:
            say(OK, "backend and frontend agree on the Supabase project")
    return bev, fev


def step_schema() -> bool:
    """Probe the database the way the app does, so a missing migration is named."""
    if not VENV_PY.exists():
        say(SKIP, "database schema", "no venv yet")
        return False
    probe = (
        "import sys; sys.path.insert(0,'.')\n"
        "from core.db.store import JobStore\n"
        "s = JobStore()\n"
        "try:\n"
        "    out = {}\n"
        "    out['postings'] = s.posting_count()\n"
        "    out['roles'] = len(s.roles())\n"
        "    out['provenance'] = s.provenance('IN')\n"
        "    print('PROBE_OK ' + __import__('json').dumps(out))\n"
        "finally:\n"
        "    s.close()\n"
    )
    code, out = run([str(VENV_PY), "-c", probe], BACKEND, timeout=180)
    if "PROBE_OK" in out:
        data = json.loads(out.split("PROBE_OK", 1)[1].strip().splitlines()[0])
        say(OK, "database schema and RPCs",
            f"{data['postings']} postings, {data['roles']} roles")
        return True
    low = out.lower()
    if "get_market_provenance" in low:
        say(FAIL, "migration 0004 not applied",
            "apply backend/supabase/migrations/0004_market_provenance.sql")
    elif "does not exist" in low or "pgrst" in low or "relation" in low:
        say(FAIL, "database schema missing",
            "apply ALL files in backend/supabase/migrations/ in order - this is "
            "the step most often skipped, and everything fails opaquely without it")
    else:
        say(FAIL, "cannot reach the database", out.strip()[-300:])
    return False


def step_seed(check: bool, schema_ok: bool) -> None:
    if not schema_ok:
        say(SKIP, "market data", "schema not ready")
        return
    code, out = run([str(VENV_PY), "-c",
                     "import sys; sys.path.insert(0,'.')\n"
                     "from core.db.store import JobStore\n"
                     "s=JobStore()\n"
                     "print('COUNT', s.posting_count()); s.close()"],
                    BACKEND, timeout=180)
    n = 0
    if "COUNT" in out:
        n = int(out.split("COUNT", 1)[1].split()[0])
    if n > 0:
        say(OK, f"market data present ({n} postings)")
        return
    if check:
        say(WARN, "market data is empty",
            "seed it: cd backend && python ../scraper/naukri_cc0_ingest.py")
        return

    naukri = BACKEND / "data" / "raw" / "naukri"
    if naukri.is_dir() and any(naukri.glob("*.zip")):
        code, out = run([str(VENV_PY), "../scraper/naukri_cc0_ingest.py"], BACKEND)
        say(OK if code == 0 else FAIL, "seeded Naukri corpus",
            "" if code == 0 else out[-300:])
    else:
        say(WARN, "Naukri corpus archive not downloaded",
            "see backend/data/README.md for the one-line curl command")

    jsearch = BACKEND / "data" / "raw" / "jsearch"
    if jsearch.is_dir() and any(jsearch.glob("*.json")):
        code, out = run([str(VENV_PY), "../scraper/jsearch_feed.py", "--restore"],
                        BACKEND)
        say(OK if code == 0 else WARN, "restored live feed archive (0 API quota)",
            "" if code == 0 else out[-300:])
    else:
        say(WARN, "no live-feed archive to restore",
            "optional; costs API quota to fetch fresh")


def step_frontend(check: bool) -> None:
    if not (FRONTEND / "package.json").exists():
        say(FAIL, "frontend/package.json missing")
        return
    if (FRONTEND / "node_modules").is_dir():
        say(OK, "frontend dependencies")
        return
    if check:
        say(FAIL, "frontend dependencies missing", "run: python bootstrap.py")
        return
    if not shutil.which("npm"):
        say(FAIL, "npm not found", "install Node.js, then re-run")
        return
    print("         running npm install...")
    code, out = run(["npm", "install", "--silent"], FRONTEND)
    say(OK if code == 0 else FAIL, "frontend dependencies installed",
        "" if code == 0 else out[-400:])


# ---------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify only; make no changes")
    args = ap.parse_args()

    print(f"{'CHECKING' if args.check else 'SETTING UP'} gap-telemetry  ({ROOT})\n")
    step_python()
    step_backend_venv(args.check)
    step_backend_deps(args.check)
    step_env_files(args.check)
    schema_ok = step_schema()
    step_seed(args.check, schema_ok)
    step_frontend(args.check)

    print()
    if _problems:
        print(f"{len(_problems)} blocking problem(s):")
        for p in _problems:
            print(f"  - {p}")
    if _notes:
        print(f"{len(_notes)} warning(s):")
        for n in _notes:
            print(f"  - {n}")
    if not _problems:
        py = VENV_PY.relative_to(ROOT) if VENV_PY.exists() else Path("python")
        print("ready. Start both halves in separate terminals:")
        print(f"  cd backend  && {py.name if IS_WINDOWS else py} -m uvicorn app.main:app --reload")
        print("  cd frontend && npm run dev")
    sys.exit(1 if _problems else 0)


if __name__ == "__main__":
    main()
