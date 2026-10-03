"""
Hand judgements on packages the channel map does not recognise.

Recall cannot be computed without deciding, per package, whether the map SHOULD
have recognised it. That decision is human, so it lives here -- one line per
package with the reason recorded -- rather than inside the measurement script,
where it would read as a result instead of a judgement. It is reviewable by the
mentor and diffable when someone disagrees.

The labels are judged on one question only:

    Does declaring this package tell you something about the candidate?

`fastapi` does. `h11` does not -- nobody chooses it; it arrives because something
else needed it. That is the whole of channels.py lesson 3, and it is why a low
coverage number is not by itself a defect: most unrecognised packages SHOULD stay
unrecognised, and mapping them would turn a dependency resolver's output into a
claim about a person.

Judged on the package, never on the profile it came from: a label decided because
it would improve one candidate's score is not a label, it is a thumb on the scale.

VERDICTS

  SKILL             a real, claimable skill -> `skill` names the canonical entry
  TRANSITIVE        pulled in by something else; says nothing about the candidate
  NOT_A_SKILL       real and deliberate, but not a skill anyone claims (linters,
                    build glue, test runners' plumbing, type stubs)
  PARSER_ARTIFACT   not a dependency at all -- a TOML key or metadata field the
                    regex parser scraped. A map bug would be the wrong fix; the
                    parser is what is wrong, and these are tracked so the noise
                    floor is visible rather than assumed

A SKILL verdict whose canonical name is absent from the taxonomy is reported
separately by the measurement script: the map cannot attach a channel to a skill
that does not exist, so it is lane C's FR-18 rather than a map defect.
"""

from __future__ import annotations

from dataclasses import dataclass


class Verdict:
    SKILL = "skill"
    TRANSITIVE = "transitive"
    NOT_A_SKILL = "not_a_skill"
    PARSER_ARTIFACT = "parser_artifact"
    #: Assigned by the measurement script, never written here.
    UNLABELLED = "unlabelled"
    NO_TAXONOMY_ENTRY = "no_taxonomy_entry"


@dataclass(frozen=True)
class Label:
    verdict: str
    skill: str = ""
    note: str = ""


def _skill(canonical: str, note: str = "") -> Label:
    return Label(Verdict.SKILL, canonical, note)


def _transitive(of: str) -> Label:
    return Label(Verdict.TRANSITIVE, note=f"pulled in by {of}")


def _not_a_skill(what: str) -> Label:
    return Label(Verdict.NOT_A_SKILL, note=what)


def _parser(what: str) -> Label:
    return Label(Verdict.PARSER_ARTIFACT, note=what)


LABELS: dict[str, Label] = {
    # ---------------------------------------------------------------- transitive
    # The six named in channels.py lesson 3, which is where this list started.
    "anyio": _transitive("starlette / httpx"),
    "h11": _transitive("uvicorn / httpx"),
    "idna": _transitive("requests / httpx"),
    "typing_extensions": _transitive("pydantic and most typed libraries"),
    "typing-extensions": _transitive("pydantic and most typed libraries"),
    "pydantic_core": _transitive("pydantic"),
    "pydantic-core": _transitive("pydantic"),
    "starlette": _transitive("fastapi"),
    "certifi": _transitive("requests / httpx"),
    "charset-normalizer": _transitive("requests"),
    "urllib3": _transitive("requests"),
    "six": _transitive("older Python libraries"),
    "setuptools": _transitive("the build toolchain"),
    "wheel": _transitive("the build toolchain"),
    "pip": _transitive("the build toolchain"),
    "packaging": _transitive("setuptools and most build tooling"),
    "sniffio": _transitive("anyio"),
    "click": _transitive("uvicorn / flask"),
    "itsdangerous": _transitive("flask"),
    "werkzeug": _transitive("flask"),
    "jinja2": _transitive("flask / fastapi templates"),
    "markupsafe": _transitive("jinja2"),
    "annotated-types": _transitive("pydantic"),
    "attrs": _transitive("many libraries"),
    "colorama": _transitive("click on Windows"),
    "tzdata": _transitive("pandas / django"),
    "python-dateutil": _transitive("pandas"),
    "pytz": _transitive("pandas / django"),
    "regex": _transitive("nltk / transformers"),
    "tqdm": _transitive("huggingface and ML libraries"),
    "pyyaml": _transitive("many libraries"),
    "requests-oauthlib": _transitive("auth libraries"),

    # ------------------------------------------------------------- not a skill
    "dotenv": _not_a_skill("config loading, one line of glue"),
    "python-dotenv": _not_a_skill("config loading, one line of glue"),
    "black": _not_a_skill("formatter; a habit, not a skill anyone claims"),
    "ruff": _not_a_skill("linter"),
    "flake8": _not_a_skill("linter"),
    "isort": _not_a_skill("import sorter"),
    "mypy": _not_a_skill("type checker"),
    "eslint": _not_a_skill("linter"),
    "prettier": _not_a_skill("formatter"),
    # npm-only, so it evidences the runtime even though "nodemon" is not itself a
    # claimable skill. The map already counts it for Node.js.
    "nodemon": _skill("Node.js", "npm-only dev-server reloader"),
    "concurrently": _not_a_skill("npm script glue"),
    "cross-env": _not_a_skill("npm script glue"),
    "rimraf": _not_a_skill("npm script glue"),
    "autoprefixer": _not_a_skill("postcss plugin, installed with tailwind"),
    "postcss": _not_a_skill("css toolchain, installed with tailwind"),

    # ------------------------------------ transitive, measured 2026-10-03
    "joblib": _transitive("scikit-learn"),
    "scipy": _transitive("scikit-learn and the scientific stack"),
    "threadpoolctl": _transitive("scikit-learn"),
    "blinker": _transitive("flask"),
    "greenlet": _transitive("sqlalchemy"),
    "python-multipart": _transitive("fastapi form handling"),
    "cffi": _transitive("cryptography"),
    "pycparser": _transitive("cffi"),
    "multidict": _transitive("aiohttp"),
    "yarl": _transitive("aiohttp"),
    "frozenlist": _transitive("aiohttp"),
    "aiosignal": _transitive("aiohttp"),
    "filelock": _transitive("torch and huggingface"),
    "fsspec": _transitive("torch and huggingface"),
    "sympy": _transitive("torch"),
    "networkx": _transitive("torch"),
    "mpmath": _transitive("sympy"),
    "safetensors": _transitive("transformers"),
    "tokenizers": _transitive("transformers"),
    # Arrives with transformers, but is also declared directly to use the Hub, and
    # the map already counts it for "Hugging Face". Judged as a skill to stay
    # consistent with the map rather than to flatter the number.
    "huggingface-hub": _skill("Hugging Face", "the Hub client, declared directly too"),
    "nanoid": _transitive("postcss"),
    "picocolors": _transitive("postcss"),
    "source-map-js": _transitive("postcss"),
    "esbuild": _transitive("vite"),
    "rollup": _transitive("vite"),
    "scheduler": _transitive("react-dom"),
    "loose-envify": _transitive("react"),
    "js-tokens": _transitive("loose-envify"),

    # ------------------------------------ not a skill, measured 2026-10-03
    # Real, deliberate dependencies that nobody claims as a skill. Mapping these
    # would turn "wrote an HTTP call" into a verified competency.
    "requests": _not_a_skill("an HTTP client; the claimable skill is Python, already "
                             "evidenced by the language itself"),
    "httpx": _not_a_skill("an HTTP client, like requests"),
    "axios": _not_a_skill("an HTTP client, like requests"),
    "aiohttp": _not_a_skill("an HTTP client"),
    "gunicorn": _not_a_skill("a WSGI server; deployment glue, not a claimed skill"),
    "waitress": _not_a_skill("a WSGI server"),
    "pillow": _not_a_skill("image file I/O. Computer Vision needs more than decoding a "
                           "JPEG, and crediting it would be the heuristic-dressed-as-"
                           "evidence trap channels.py warns about"),
    "cors": _not_a_skill("one middleware line"),
    "flask-cors": _not_a_skill("one middleware line"),
    "body-parser": _not_a_skill("express middleware"),
    "cookie-parser": _not_a_skill("express middleware"),
    "morgan": _not_a_skill("express request logger"),
    "helmet": _not_a_skill("express header middleware"),
    "@types/node": _not_a_skill("type stubs"),
    "@types/react": _not_a_skill("type stubs"),
    "@types/react-dom": _not_a_skill("type stubs"),
    "@types/express": _not_a_skill("type stubs"),
    "@eslint/js": _not_a_skill("eslint config"),
    "eslint-plugin-react-hooks": _not_a_skill("eslint config"),
    "eslint-plugin-react-refresh": _not_a_skill("eslint config"),
    "globals": _not_a_skill("eslint config"),
    "typescript-eslint": _not_a_skill("eslint config"),
    "@tailwindcss/postcss": _not_a_skill("the tailwind build plugin, installed with it"),
    "@tailwindcss/vite": _not_a_skill("the tailwind build plugin, installed with it"),
    "criterion": _not_a_skill("a Rust benchmark harness"),
    # The map counts test runners for "Unit Testing" and these labels follow it.
    # Worth a mentor question rather than a silent change: a `pytest` line in a
    # requirements file often arrives with a template, so granting it E3 DECLARED
    # -- the strongest unauthored tier -- is generous. The file-tree signal
    # (a tests/ directory) is the stronger half of that spec.
    "pytest": _skill("Unit Testing", "a test runner; weak on its own"),
    "vitest": _skill("Unit Testing", "a test runner; weak on its own"),
    "jest": _skill("Unit Testing", "a test runner; weak on its own"),

    # ------------------------------- parser artifacts, measured 2026-10-03
    # NOT dependencies. parse_pyproject_toml and parse_cargo_toml scrape any
    # `key = value` line, so TOML metadata and table names arrive looking like
    # packages. They cannot cause a false verification -- no channel lists a
    # package called "version" -- but they inflate the denominator, which made
    # coverage read worse than it is. Labelled so the noise floor is a measured
    # number instead of an assumption, and so fixing the parser is visible.
    "name": _parser("[project] name"),
    "version": _parser("[project] version"),
    "description": _parser("[project] description"),
    "authors": _parser("[project] authors"),
    "license": _parser("[project] license"),
    "keywords": _parser("[project] keywords"),
    "classifiers": _parser("[project] classifiers"),
    "readme": _parser("[project] readme"),
    "requires-python": _parser("[project] requires-python"),
    "dependencies": _parser("the [project.dependencies] table name"),
    "dev": _parser("the [dependency-groups] table name"),
    "build-backend": _parser("[build-system] build-backend"),
    "requires": _parser("[build-system] requires"),
    "edition": _parser("Cargo.toml [package] edition"),
    "repository": _parser("Cargo.toml [package] repository"),
    "homepage": _parser("Cargo.toml [package] homepage"),
    "harness": _parser("Cargo.toml [[bench]] harness"),
    "codegen-units": _parser("Cargo.toml [profile] codegen-units"),
    "lto": _parser("Cargo.toml [profile] lto"),
    "opt-level": _parser("Cargo.toml [profile] opt-level"),
    "panic": _parser("Cargo.toml [profile] panic"),
    "strip": _parser("Cargo.toml [profile] strip"),
    "features": _parser("a dependency's features list"),
    "workspace": _parser("Cargo.toml [workspace]"),
    "members": _parser("Cargo.toml [workspace] members"),
    "main": _parser("package.json entry point"),
    "type": _parser("package.json module type"),
    "private": _parser("package.json private flag"),
    "scripts": _parser("package.json scripts table"),

    # ----------------------------------------- skills, measured 2026-10-03
    # Packages that DO say something, with the canonical skill they say it about.
    # A name the taxonomy does not contain is reported as lane C's problem rather
    # than fixed by inventing a channel for a skill that does not exist.
    "typescript": _skill("TypeScript", "declared wherever TS is actually used"),
    "ts-node": _skill("TypeScript"),
    "sqlalchemy": _skill("SQL", "an ORM is direct evidence of relational database work"),
    "psycopg2": _skill("PostgreSQL"),
    "psycopg2-binary": _skill("PostgreSQL"),
    "asyncpg": _skill("PostgreSQL"),
    "react-router-dom": _skill("React", "React-only; cannot be used without it"),
    "lucide-react": _skill("React", "React-only icon set"),
    "@vitejs/plugin-react": _skill("React", "React-only build plugin"),
    "react-icons": _skill("React", "React-only"),
    "framer-motion": _skill("React", "React-only animation library"),
    "@openzeppelin/contracts": _skill("Blockchain", "a Solidity contract library"),
    "@nomicfoundation/hardhat-toolbox": _skill("Blockchain", "the Hardhat toolchain"),
    "serde": _skill("Rust", "Rust-only"),
    "serde_json": _skill("Rust", "Rust-only"),
    "clap": _skill("Rust", "Rust-only"),
    "anyhow": _skill("Rust", "Rust-only"),
    "tokio": _skill("Rust", "Rust-only"),
    # These two LOOK like map fixes and are not. Both were caught by trying the
    # fix and seeing what it would have claimed.
    #
    # bcrypt is deliberate, specific work, but the only taxonomy entry that fits
    # is "Cybersecurity", which channels.py marks unverifiable by design -- a
    # domain, not a declarable artifact. Attaching packages to it would quietly
    # turn a concept into something checkable.
    "bcrypt": _skill("Authentication", "password hashing, chosen deliberately"),
    "bcryptjs": _skill("Authentication", "password hashing, chosen deliberately"),
    # beautifulsoup4 is web scraping, and the taxonomy files "Web Scraping" as an
    # ALIAS OF SELENIUM. Mapping it would verify Selenium for a candidate who has
    # never used Selenium -- a false verification, which is the worst thing this
    # project can produce. The conflation is the defect, not the missing channel.
    "beautifulsoup4": _skill("Web Scraping", "scraping without a browser driver"),
    "bs4": _skill("Web Scraping", "alias of beautifulsoup4"),

    # Real and commonly claimed, but ABSENT from the 96-skill taxonomy, so no
    # channel can be attached to them. Handed to lane C (FR-18) rather than
    # papered over here.
    "streamlit": _skill("Streamlit", "no canonical entry"),
    "vite": _skill("Vite", "no canonical entry"),
    "pydantic": _skill("Pydantic", "no canonical entry"),
    "zod": _skill("Zod", "no canonical entry"),
    "prisma": _skill("Prisma", "no canonical entry"),
    "@prisma/client": _skill("Prisma", "no canonical entry"),
    "drizzle-orm": _skill("Drizzle", "no canonical entry"),
    # Corrected: both ARE in the taxonomy and in the map. The first labels guessed
    # otherwise, which the labels-versus-map invariant test caught.
    "nltk": _skill("Natural Language Processing"),
    "spacy": _skill("spaCy"),
    "pydantic-settings": _skill("Pydantic", "no canonical entry"),

    # ---------------- second pass: the head after the parser noise was removed
    # Fixing the TOML parser and the map moved 187 pseudo-packages out of the
    # distribution, which promoted thirteen real names into the head. Judged on
    # the same question as everything above.
    "rayon": _skill("Rust", "Rust-only"),
    "thiserror": _skill("Rust", "Rust-only"),
    "tracing": _skill("Rust", "Rust-only"),
    "tracing-subscriber": _skill("Rust", "Rust-only"),
    "tsx": _skill("TypeScript", "a TypeScript runner"),
    "eslint-config-next": _skill("Next.js", "Next.js-only"),
    "httpcore": _transitive("httpx"),
    "soupsieve": _transitive("beautifulsoup4"),
    "oxlint": _not_a_skill("linter"),
    "commander": _not_a_skill("argument parsing, a few lines of glue"),
    "@testing-library/react": _not_a_skill("a test utility; see pytest"),
    "@testing-library/jest-dom": _not_a_skill("a test utility; see pytest"),
    "@testing-library/user-event": _not_a_skill("a test utility; see pytest"),
    "clsx": _not_a_skill("string concatenation for class names"),
    "distro": _transitive("the openai SDK"),
    "flask-sqlalchemy": _skill("SQL", "the Flask binding for an ORM"),

    # ------------------- third pass: the frontier at exactly 3 declarations
    # Where labelling stops. Below three declarations the tail is ~250 names seen
    # once or twice, and judging them could not move any number in the report.
    "jsonwebtoken": _skill("Authentication", "no canonical entry; see bcrypt"),
    "pyjwt": _skill("Authentication", "no canonical entry; see bcrypt"),
    "passlib": _skill("Authentication", "no canonical entry; see bcrypt"),
    "jupyter": _skill("Jupyter", "no canonical entry, although the plan already treats "
                                 "*.ipynb as a file signal (FR-3)"),
    "notebook": _skill("Jupyter", "no canonical entry"),
    "react-scripts": _skill("React", "Create React App; React-only"),
    "tailwind-merge": _skill("Tailwind CSS", "Tailwind-only"),
    "typing-inspection": _transitive("pydantic 2.12+"),
    "types-pyyaml": _not_a_skill("type stubs"),
    "psutil": _not_a_skill("reads system metrics; a utility call"),
    "pytest-asyncio": _not_a_skill("a test runner plugin; see pytest"),
    "web-vitals": _not_a_skill("shipped in the Create React App template, unchosen"),

    # ----------- fourth pass: the DENSE frame, which is a different ecosystem
    # The population frame is web. The dense frame -- visibly active accounts, who
    # Dataset A will actually be drawn from -- is substantially Android, Kotlin and
    # React Native, and the map had almost nothing for any of them. These arrive
    # through parse_build_gradle, which keeps the artifactId from a
    # `group:artifact:version` coordinate.
    "appcompat": _skill("Android Development", "AndroidX"),
    "appcompat-v7": _skill("Android Development", "the old Android support library"),
    "recyclerview": _skill("Android Development", "AndroidX"),
    "cardview": _skill("Android Development", "AndroidX"),
    "constraintlayout": _skill("Android Development", "AndroidX"),
    "core-ktx": _skill("Android Development", "AndroidX"),
    "espresso-core": _skill("Android Development", "the Android UI test framework"),
    "material": _skill("Android Development", "Material Components for Android"),
    "lifecycle-runtime-ktx": _skill("Android Development", "AndroidX"),
    "activity-compose": _skill("Android Development", "Jetpack Compose"),
    "gradle": _skill("Android Development",
                     "in practice this is com.android.tools.build:gradle, the "
                     "Android Gradle plugin, not Gradle itself"),
    "google-services": _skill("Firebase", "the Google Services Gradle plugin"),
    "firebase-database": _skill("Firebase", "the Realtime Database SDK"),
    "firebase-auth": _skill("Firebase"),
    "firebase-firestore": _skill("Firebase"),
    "gson": _skill("Java", "a Java/Android JSON library"),
    "retrofit": _skill("Java", "the standard Android HTTP client, Java/Kotlin only"),
    "react-native-screens": _skill("React Native", "React-Native-only"),
    "react-native-safe-area-context": _skill("React Native", "React-Native-only"),
    "react-native-gesture-handler": _skill("React Native", "React-Native-only"),
    "metro-react-native-babel-preset": _skill("React Native", "the RN bundler preset"),
    "android-jsc": _skill("React Native", "the RN JavaScript engine"),
    "android-jsc-intl": _skill("React Native", "the RN JavaScript engine"),
    # Kotlin is NOT in the 96-skill taxonomy. The map currently treats the Kotlin
    # LANGUAGE as evidence of "Android Development", which is a conflation --
    # Kotlin is also a server-side language -- so these are reported as lane C's
    # gap rather than quietly folded into Android.
    "kotlin-gradle-plugin": _skill("Kotlin", "no canonical entry"),
    "kotlin-stdlib-jdk7": _skill("Kotlin", "no canonical entry"),
    "kotlin-stdlib": _skill("Kotlin", "no canonical entry"),
    "@babel/core": _not_a_skill("a transpiler, installed by the framework"),
    "@babel/runtime": _transitive("babel"),
    "babel-jest": _not_a_skill("test plumbing"),
    "react-test-renderer": _not_a_skill("a test utility; see pytest"),
    "@react-native-community/eslint-config": _not_a_skill("eslint config"),
    "docsify-cli": _not_a_skill("a docs site generator; writing docs is good practice, "
                                "not a claimed technical skill"),
    "core": _parser("too generic to attribute -- 'core' is the artifactId of many "
                    "unrelated Gradle coordinates, so the group is what carried the "
                    "meaning and parse_build_gradle discards it"),
}
