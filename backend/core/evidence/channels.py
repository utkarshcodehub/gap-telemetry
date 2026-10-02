"""
Skill -> evidence-channel map: which artifacts could prove each skill.

`verification_coverage` (EVIDENCE_MODEL section 8.5) asks whether we retrieved an
artifact channel that COULD have carried a skill's signal. That question is
unanswerable without this map, so `CONTRADICTED` cannot fire until it exists.

Three channels, which also set the tier a hit can reach:

    LANGUAGE   GitHub's computed language-byte statistics        -> E2 PRESENT
    FILE_TREE  a path or filename in the repository tree         -> E2 PRESENT
    MANIFEST   a declared dependency in a package manifest       -> E3 DECLARED

MANIFEST outranks the others because a declared dependency is the hardest of the
three to fabricate: the toolchain would break. A filename can be created by
anyone, but it still beats README prose (E1), which the candidate simply wrote.

**Some skills are deliberately NOT artifact-verifiable** (`verifiable=False`).
Being honest about this is the point: a candidate must not read as low-coverage
because we cannot check "System Design", and `CONTRADICTED` must never fire for a
skill no artifact could have evidenced (EC-9). Three groups:

  - Concepts and fundamentals -- "Data Structures & Algorithms", "DBMS". Every
    repo uses data structures; none declares them.
  - Architecture and practice -- "Microservices", "REST API", "ETL". Real skills
    that leave no single reliable artifact. Guessing from a docker-compose file
    with three services would be a heuristic dressed as evidence.
  - Soft skills -- excluded from the demand basket anyway, listed for completeness.

Keyed by canonical skill name so it extends with Member C's induced taxonomy
without waiting for it. `validate_against_taxonomy()` FAILS on any taxonomy skill
missing an entry, which is what stops an expanded taxonomy silently losing
verifiability for its new skills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Channel(str, Enum):
    LANGUAGE = "language"
    FILE_TREE = "file_tree"
    MANIFEST = "manifest"


@dataclass(frozen=True)
class ChannelSpec:
    #: GitHub language names (its own `language` field / linguist stats).
    languages: tuple[str, ...] = ()
    #: Exact filenames, matched case-insensitively against the basename.
    files: tuple[str, ...] = ()
    #: Path suffixes, e.g. ".tf". Matched against the full path.
    extensions: tuple[str, ...] = ()
    #: Path fragments, e.g. ".github/workflows/".
    path_contains: tuple[str, ...] = ()
    #: Dependency names as they appear in a manifest, lowercased.
    packages: tuple[str, ...] = ()
    #: False when no artifact can evidence this skill (section 8.5 / EC-9).
    verifiable: bool = True
    #: Why, when verifiable is False. Shown to the candidate so an unverifiable
    #: skill reads as a category, not a failure.
    unverifiable_reason: str = ""

    @property
    def channels(self) -> frozenset[Channel]:
        out = set()
        if self.languages:
            out.add(Channel.LANGUAGE)
        if self.files or self.extensions or self.path_contains:
            out.add(Channel.FILE_TREE)
        if self.packages:
            out.add(Channel.MANIFEST)
        return frozenset(out)


def _concept(reason: str) -> ChannelSpec:
    return ChannelSpec(verifiable=False, unverifiable_reason=reason)


_CONCEPT = "a concept, not an artifact: every project uses it, none declares it"
_PRACTICE = "an architectural practice with no single reliable artifact"
_SOFT = "a soft skill; not evidenced by code by design"

CHANNELS: dict[str, ChannelSpec] = {
    # ---------------------------------------------------- programming_language
    "C": ChannelSpec(languages=("C",), extensions=(".c",), files=("makefile",)),
    "C++": ChannelSpec(languages=("C++",), extensions=(".cpp", ".cc", ".cxx", ".hpp"),
                       files=("cmakelists.txt",)),
    "Go": ChannelSpec(languages=("Go",), extensions=(".go",), files=("go.mod", "go.sum")),
    "Java": ChannelSpec(languages=("Java",), extensions=(".java",),
                        files=("pom.xml", "build.gradle", "build.gradle.kts")),
    "JavaScript": ChannelSpec(languages=("JavaScript",), extensions=(".js", ".mjs", ".cjs")),
    "Python": ChannelSpec(languages=("Python",), extensions=(".py",),
                          files=("requirements.txt", "pyproject.toml", "setup.py", "pipfile")),
    "R": ChannelSpec(languages=("R",), extensions=(".r", ".rmd"), files=("description",)),
    "Rust": ChannelSpec(languages=("Rust",), extensions=(".rs",), files=("cargo.toml",)),
    "SQL": ChannelSpec(languages=("SQL", "PLpgSQL", "TSQL"), extensions=(".sql",)),
    "TypeScript": ChannelSpec(languages=("TypeScript",), extensions=(".ts", ".tsx"),
                              files=("tsconfig.json",)),

    # ------------------------------------------------------------------ frontend
    "Angular": ChannelSpec(files=("angular.json",), packages=("@angular/core", "@angular/cli")),
    "CSS": ChannelSpec(languages=("CSS", "SCSS", "Less"), extensions=(".css", ".scss", ".sass")),
    "HTML": ChannelSpec(languages=("HTML",), extensions=(".html", ".htm")),
    "Next.js": ChannelSpec(files=("next.config.js", "next.config.mjs", "next.config.ts"),
                           packages=("next",)),
    "React": ChannelSpec(packages=("react", "react-dom")),
    "Redux": ChannelSpec(packages=("redux", "@reduxjs/toolkit", "react-redux")),
    "Tailwind CSS": ChannelSpec(files=("tailwind.config.js", "tailwind.config.ts"),
                                packages=("tailwindcss",)),
    "Vue.js": ChannelSpec(languages=("Vue",), extensions=(".vue",), packages=("vue",)),

    # ------------------------------------------------------------------- backend
    "Django": ChannelSpec(files=("manage.py",), packages=("django", "djangorestframework")),
    "Express.js": ChannelSpec(packages=("express",)),
    "FastAPI": ChannelSpec(packages=("fastapi", "uvicorn")),
    "Flask": ChannelSpec(packages=("flask",)),
    "GraphQL": ChannelSpec(extensions=(".graphql", ".gql"),
                           packages=("graphql", "apollo-server", "graphene", "strawberry-graphql")),
    "Microservices": _concept(_PRACTICE),
    "Node.js": ChannelSpec(files=("package.json", "package-lock.json"), packages=("express", "nodemon")),
    "REST API": _concept(_PRACTICE),
    "Spring Boot": ChannelSpec(files=("pom.xml", "build.gradle"),
                               packages=("spring-boot-starter", "spring-boot-starter-web")),
    "WebSockets": ChannelSpec(packages=("socket.io", "ws", "websockets", "socket.io-client")),

    # -------------------------------------------------------------- cloud_devops
    "AWS": ChannelSpec(packages=("boto3", "aws-sdk", "@aws-sdk/client-s3", "awscli"),
                       path_contains=(".aws/",)),
    "Azure": ChannelSpec(packages=("azure-identity", "azure-storage-blob", "@azure/identity"),
                         files=("azure-pipelines.yml",)),
    "CI/CD": ChannelSpec(path_contains=(".github/workflows/", ".circleci/"),
                         files=(".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml",
                                ".travis.yml")),
    "Docker": ChannelSpec(files=("dockerfile", "docker-compose.yml", "docker-compose.yaml",
                                 ".dockerignore", "compose.yaml")),
    "Git": ChannelSpec(files=(".gitignore", ".gitattributes")),
    "Google Cloud": ChannelSpec(packages=("google-cloud-storage", "google-cloud-bigquery",
                                          "@google-cloud/storage"),
                                files=("app.yaml", "cloudbuild.yaml")),
    "Kubernetes": ChannelSpec(files=("chart.yaml", "kustomization.yaml", "skaffold.yaml"),
                              path_contains=("k8s/", "kubernetes/", "helm/"),
                              packages=("kubernetes", "@kubernetes/client-node")),
    "Linux": _concept("an operating environment, not an artifact in a repository"),
    "Nginx": ChannelSpec(files=("nginx.conf", "default.conf")),
    "Terraform": ChannelSpec(languages=("HCL",), extensions=(".tf", ".tfvars")),

    # ------------------------------------------------------------------ database
    "Elasticsearch": ChannelSpec(packages=("elasticsearch", "@elastic/elasticsearch")),
    "Firebase": ChannelSpec(files=("firebase.json", "firestore.rules"),
                            packages=("firebase", "firebase-admin")),
    "MongoDB": ChannelSpec(packages=("pymongo", "mongoose", "mongodb", "motor")),
    "MySQL": ChannelSpec(packages=("mysqlclient", "mysql2", "pymysql", "mysql-connector-python")),
    "PostgreSQL": ChannelSpec(packages=("psycopg2", "psycopg2-binary", "psycopg", "pg", "asyncpg")),
    "Redis": ChannelSpec(packages=("redis", "ioredis", "redis-py")),
    "SQLite": ChannelSpec(extensions=(".sqlite", ".sqlite3", ".db"),
                          packages=("better-sqlite3", "aiosqlite")),
    "Supabase": ChannelSpec(packages=("supabase", "@supabase/supabase-js"),
                            path_contains=("supabase/",)),
    "Vector Databases": ChannelSpec(packages=("pinecone-client", "weaviate-client", "chromadb",
                                              "qdrant-client", "faiss-cpu", "pgvector")),

    # ---------------------------------------------------------------------- data
    "Airflow": ChannelSpec(packages=("apache-airflow",), path_contains=("dags/",)),
    "Apache Kafka": ChannelSpec(packages=("kafka-python", "confluent-kafka", "kafkajs")),
    "Apache Spark": ChannelSpec(packages=("pyspark", "findspark")),
    "Big Data": _concept("an umbrella term; the concrete tools are detected individually"),
    "Data Analysis": _concept("an umbrella term; the concrete libraries are detected individually"),
    "Data Visualization": ChannelSpec(packages=("matplotlib", "seaborn", "plotly", "bokeh",
                                                "altair", "d3", "chart.js", "recharts")),
    "ETL": _concept(_PRACTICE),
    "Excel": ChannelSpec(extensions=(".xlsx", ".xls"), packages=("openpyxl", "xlrd", "xlsxwriter")),
    "NumPy": ChannelSpec(packages=("numpy",)),
    "Pandas": ChannelSpec(packages=("pandas",)),
    "Power BI": ChannelSpec(extensions=(".pbix", ".pbit")),
    "Statistics": _concept(_CONCEPT),
    "Tableau": ChannelSpec(extensions=(".twb", ".twbx", ".hyper")),

    # -------------------------------------------------------------------- ml_ai
    "AI Agents": ChannelSpec(packages=("langgraph", "crewai", "autogen", "pyautogen",
                                       "langchain-core")),
    "Computer Vision": ChannelSpec(packages=("opencv-python", "torchvision", "ultralytics",
                                             "mediapipe", "albumentations")),
    "Deep Learning": ChannelSpec(packages=("torch", "tensorflow", "keras", "jax")),
    "Fine-tuning": ChannelSpec(packages=("peft", "trl", "bitsandbytes", "unsloth")),
    "Hugging Face": ChannelSpec(packages=("transformers", "huggingface-hub", "datasets",
                                          "accelerate")),
    "LangChain": ChannelSpec(packages=("langchain", "langchain-community", "langchain-openai")),
    "Large Language Models": ChannelSpec(packages=("openai", "anthropic", "transformers",
                                                   "litellm", "vllm", "ollama")),
    "MLOps": ChannelSpec(files=("dvc.yaml", "mlproject"),
                         packages=("mlflow", "wandb", "dvc", "bentoml", "kedro")),
    "Machine Learning": ChannelSpec(packages=("scikit-learn", "torch", "tensorflow", "xgboost",
                                              "lightgbm")),
    "Natural Language Processing": ChannelSpec(packages=("spacy", "nltk", "transformers",
                                                         "gensim", "textblob")),
    "Prompt Engineering": _concept("a practice expressed inside source files, with no "
                                   "declarable artifact of its own"),
    "PyTorch": ChannelSpec(packages=("torch", "pytorch-lightning", "torchvision")),
    "RAG": ChannelSpec(packages=("llama-index", "langchain", "chromadb", "faiss-cpu",
                                 "sentence-transformers")),
    "TensorFlow": ChannelSpec(packages=("tensorflow", "tensorflow-cpu", "keras")),
    "XGBoost": ChannelSpec(packages=("xgboost",)),
    "scikit-learn": ChannelSpec(packages=("scikit-learn", "sklearn")),
    "spaCy": ChannelSpec(packages=("spacy",)),

    # -------------------------------------------------------------------- mobile
    "Android Development": ChannelSpec(languages=("Kotlin",),
                                       files=("androidmanifest.xml", "build.gradle.kts"),
                                       path_contains=("app/src/main/",)),
    "Flutter": ChannelSpec(languages=("Dart",), files=("pubspec.yaml",), extensions=(".dart",)),
    "React Native": ChannelSpec(files=("metro.config.js", "app.json"),
                                packages=("react-native", "expo")),

    # ------------------------------------------------------------- cs_fundamentals
    "Computer Networks": _concept(_CONCEPT),
    "DBMS": _concept(_CONCEPT),
    "Data Structures & Algorithms": _concept(_CONCEPT),
    "Object-Oriented Programming": _concept(_CONCEPT),
    "Operating Systems": _concept(_CONCEPT),
    "System Design": _concept(_PRACTICE),

    # ------------------------------------------------------------------- testing
    "Postman": ChannelSpec(extensions=(".postman_collection.json", ".postman_environment.json")),
    "Selenium": ChannelSpec(packages=("selenium", "webdriver-manager", "selenium-webdriver")),
    "Unit Testing": ChannelSpec(path_contains=("tests/", "test/", "__tests__/", "spec/"),
                                files=("pytest.ini", "jest.config.js", "conftest.py"),
                                packages=("pytest", "jest", "mocha", "vitest", "unittest2",
                                          "junit")),

    # ------------------------------------------------------------------ emerging
    "Blockchain": ChannelSpec(languages=("Solidity",), extensions=(".sol",),
                              files=("hardhat.config.js", "truffle-config.js"),
                              packages=("web3", "ethers", "hardhat")),
    "Cybersecurity": _concept("a domain, not a declarable artifact; concrete tools would "
                               "need their own taxonomy entries"),
    "IoT": _concept("a domain spanning hardware and firmware that a repository tree "
                     "does not reliably reveal"),

    # ---------------------------------------------------------------- soft_skill
    "Agile": _concept(_SOFT),
    "Communication": _concept(_SOFT),
    "Leadership": _concept(_SOFT),
    "Teamwork": _concept(_SOFT),
}


class ChannelMapIncomplete(RuntimeError):
    """Raised when a taxonomy skill has no channel entry."""


def spec_for(skill: str) -> ChannelSpec | None:
    return CHANNELS.get(skill)


def is_verifiable_by_design(skill: str) -> bool:
    """Unknown skills default to NOT verifiable.

    Fails closed on purpose: treating an unmapped skill as checkable would let
    `CONTRADICTED` fire on a skill we have no way to detect, which is the one
    error this system must not make.
    """
    spec = CHANNELS.get(skill)
    return bool(spec and spec.verifiable)


def validate_against_taxonomy(canonical_skills: set[str]) -> None:
    """Fail if any taxonomy skill lacks an entry.

    This is the guard that makes the map extend with Member C's induced taxonomy
    rather than silently leaving new skills unverifiable.
    """
    missing = sorted(canonical_skills - set(CHANNELS))
    if missing:
        raise ChannelMapIncomplete(
            f"{len(missing)} taxonomy skill(s) have no evidence-channel entry: "
            f"{missing}\nAdd each to core/evidence/channels.py -- either with "
            f"detectors, or as _concept('<why no artifact can evidence it>'). "
            f"An unmapped skill silently becomes unverifiable and can never be "
            f"VERIFIED or CONTRADICTED."
        )
