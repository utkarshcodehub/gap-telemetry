"""Synthetic job-posting generator — probability-weighted, seeded, realistic."""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.db.store import JobStore, PostingRecord  # noqa: E402
from ingest import ingest_postings                  # noqa: E402

ROLE_SKILL_POOLS: dict[str, list[tuple[list[str], float]]] = {
    "ai ml engineer": [
        (["Python", "python"], 0.92), (["Machine Learning", "ML"], 0.85),
        (["Deep Learning", "neural networks"], 0.55), (["TensorFlow", "Keras"], 0.45),
        (["PyTorch"], 0.48), (["scikit-learn", "sklearn"], 0.40),
        (["NLP", "natural language processing"], 0.38),
        (["LLMs", "GenAI", "large language models"], 0.52),
        (["prompt engineering"], 0.25), (["RAG", "retrieval augmented generation"], 0.22),
        (["LangChain"], 0.20), (["Hugging Face", "huggingface"], 0.18),
        (["SQL"], 0.60), (["Pandas"], 0.45), (["NumPy"], 0.35), (["Docker"], 0.35),
        (["AWS", "Azure", "GCP"], 0.40), (["Git", "GitHub"], 0.50),
        (["FastAPI", "Flask"], 0.30), (["MLOps", "MLflow"], 0.28),
        (["computer vision", "OpenCV"], 0.25), (["statistics", "statistical analysis"], 0.30),
        (["vector databases", "Pinecone", "ChromaDB"], 0.15), (["communication skills"], 0.40),
        (["DSA", "data structures"], 0.30),
    ],
    "data analyst": [
        (["SQL", "advanced SQL"], 0.90), (["Excel", "MS Excel", "advanced Excel"], 0.80),
        (["Power BI", "PowerBI"], 0.65), (["Tableau"], 0.45), (["Python", "python"], 0.60),
        (["Pandas"], 0.30), (["data visualization", "matplotlib"], 0.40),
        (["statistics", "hypothesis testing"], 0.45), (["EDA", "exploratory data analysis"], 0.30),
        (["ETL", "data pipelines"], 0.25), (["MySQL", "PostgreSQL"], 0.30),
        (["communication skills"], 0.55), (["A/B testing"], 0.15),
        (["Machine Learning", "ML"], 0.25), (["Excel", "pivot tables", "vlookup"], 0.35),
        (["big data", "Spark"], 0.12),
    ],
    "backend developer": [
        (["Node.js", "NodeJS", "node"], 0.55), (["Python", "python"], 0.50),
        (["Java", "core Java"], 0.45), (["REST APIs", "RESTful APIs", "REST"], 0.75),
        (["SQL"], 0.60), (["MongoDB", "mongo"], 0.45), (["PostgreSQL", "postgres"], 0.35),
        (["MySQL"], 0.35), (["Express.js", "Express"], 0.40), (["Django", "DRF"], 0.25),
        (["FastAPI"], 0.20), (["Spring Boot", "springboot"], 0.30),
        (["Docker", "containerization"], 0.45), (["Kubernetes", "k8s"], 0.25),
        (["AWS", "EC2", "S3"], 0.45), (["Redis"], 0.30), (["Kafka"], 0.18),
        (["microservices"], 0.40), (["Git", "GitHub"], 0.55),
        (["CI/CD", "Jenkins", "GitHub Actions"], 0.35),
        (["system design", "distributed systems"], 0.30),
        (["DSA", "data structures and algorithms"], 0.45), (["Linux", "shell scripting"], 0.30),
        (["unit testing", "pytest", "junit"], 0.25), (["GraphQL"], 0.12),
    ],
    "full stack developer": [
        (["React", "ReactJS", "React.js"], 0.80), (["JavaScript", "JS"], 0.85),
        (["TypeScript"], 0.45), (["Node.js", "NodeJS"], 0.65), (["HTML"], 0.60),
        (["CSS", "CSS3"], 0.60), (["Next.js", "NextJS"], 0.30),
        (["Tailwind", "tailwindcss"], 0.25), (["MongoDB"], 0.45), (["SQL", "MySQL"], 0.50),
        (["Express", "Express.js"], 0.45), (["REST APIs", "RESTful"], 0.60),
        (["Redux"], 0.30), (["Git", "GitHub"], 0.55), (["AWS"], 0.30), (["Docker"], 0.28),
        (["Angular"], 0.20), (["DSA", "problem solving"], 0.35), (["Agile", "scrum"], 0.30),
        (["communication skills", "teamwork"], 0.40),
    ],
}

COMPANIES = ["TechVista Solutions", "Innovare Labs", "QuantumLeap AI", "Nexus Digital",
             "Vertex Analytics", "CodeCraft Technologies", "Stellar Systems", "PixelForge",
             "DataNest India", "CloudSprint", "NeuralPath AI", "Apex Software Services",
             "BrightHive Tech", "Zenith Infotech", "Kalpataru Digital", "Meridian Softworks",
             "OrbitShift Labs"]
LOCATIONS = ["Bengaluru", "Hyderabad", "Pune", "Noida", "Gurugram", "Mumbai", "Chennai",
             "Remote", "Bengaluru/Hyderabad", "Noida/Gurugram"]
TEMPLATES = [
    ("We are hiring a {title} to join our growing team in {location}. "
     "The ideal candidate has hands-on experience with {top_skills}. "
     "Familiarity with {rest_skills} is a strong plus. You will work on "
     "production systems, collaborate with cross-functional teams, and own features end to end."),
    ("{company} is looking for a passionate {title}. Must-have skills: {top_skills}. "
     "Good to have: {rest_skills}. You will design, build and ship real products "
     "used by thousands of users across India."),
    ("Role: {title} | Location: {location}\nKey skills: {all_skills}\n"
     "Responsibilities include building scalable solutions, writing clean maintainable "
     "code, and mentoring juniors. Freshers with strong projects are encouraged to apply."),
]
TITLES = {
    "ai ml engineer": ["AI/ML Engineer", "Machine Learning Engineer", "ML Engineer - GenAI",
                       "AI Engineer Intern", "Junior ML Engineer"],
    "data analyst": ["Data Analyst", "Business Analyst - Data", "Junior Data Analyst",
                     "Data Analyst Intern", "Analytics Associate"],
    "backend developer": ["Backend Developer", "Backend Engineer", "SDE - Backend",
                          "Junior Backend Developer", "Python Backend Developer"],
    "full stack developer": ["Full Stack Developer", "MERN Stack Developer", "SDE - Full Stack",
                             "Junior Full Stack Engineer", "React Developer"],
}
EXPERIENCE = ["0-1 Yrs", "0-2 Yrs", "1-3 Yrs", "2-4 Yrs", "Fresher"]
SALARY = ["Not Disclosed", "3-5 Lacs PA", "4-7 Lacs PA", "5-9 Lacs PA", "6-10 Lacs PA", "8-12 Lacs PA"]


def generate_posting(role: str, idx: int, rng: random.Random) -> PostingRecord:
    pool = ROLE_SKILL_POOLS[role]
    chosen: list[str] = []
    for surface_forms, prob in pool:
        if rng.random() < prob:
            chosen.append(rng.choice(surface_forms))
    rng.shuffle(chosen)
    if len(chosen) < 4:
        chosen += [rng.choice(f) for f, _ in rng.sample(pool, 4)]
    split = max(3, len(chosen) // 2)
    template = rng.choice(TEMPLATES)
    company = rng.choice(COMPANIES)
    location = rng.choice(LOCATIONS)
    title = rng.choice(TITLES[role])
    description = template.format(
        title=title, company=company, location=location,
        top_skills=", ".join(chosen[:split]), rest_skills=", ".join(chosen[split:]) or "cloud platforms",
        all_skills=", ".join(chosen),
    )
    return PostingRecord(source="synthetic", external_id=f"syn-{role.replace(' ', '')}-{idx}",
                         title=title, company=company, location=location,
                         experience=rng.choice(EXPERIENCE), salary=rng.choice(SALARY),
                         description=description, role_query=role)


def generate(count: int, seed: int, roles: list[str] | None = None) -> list[PostingRecord]:
    rng = random.Random(seed)
    roles = roles or list(ROLE_SKILL_POOLS.keys())
    per_role = count // len(roles)
    records = []
    for role in roles:
        for i in range(per_role):
            records.append(generate_posting(role, i, rng))
    return records


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    store = JobStore()
    records = generate(args.count, args.seed)
    inserted = ingest_postings(records, store)
    print(f"{len(records)} generated, {inserted} ingested. DB total: {store.posting_count()}")
    store.close()
