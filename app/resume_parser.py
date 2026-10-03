import io
import re
from pypdf import PdfReader


SKILL_DICT = {
    # languages
    "python", "javascript", "typescript", "java", "go", "golang", "rust", "ruby",
    "php", "c", "c++", "c#", "kotlin", "swift", "scala", "r", "matlab", "perl",
    "elixir", "clojure", "dart", "objective-c",
    # frontend
    "react", "vue", "angular", "svelte", "next.js", "nuxt", "redux", "tailwind",
    "html", "css", "sass", "webpack", "vite",
    # backend
    "node", "node.js", "express", "fastapi", "django", "flask", "rails",
    "spring", "spring boot", ".net", "laravel", "graphql", "rest", "grpc",
    # databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "sqlite", "dynamodb", "cassandra", "sqlalchemy", "prisma",
    # cloud / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "jenkins", "github actions", "gitlab ci",
    "circleci", "helm", "prometheus", "grafana", "datadog",
    # data / ml
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras",
    "spark", "hadoop", "airflow", "dbt", "snowflake", "bigquery", "redshift",
    "tableau", "power bi", "looker",
    # mobile
    "react native", "flutter", "ios", "android", "swiftui",
    # other
    "git", "linux", "bash", "agile", "scrum", "jira", "figma",
    "machine learning", "ml", "ai", "nlp", "computer vision",
    "rest api", "microservices", "ci/cd", "tdd", "oop",
}

SENIORITY_MAP = [
    ("principal", "principal"),
    ("staff", "staff"),
    ("lead", "lead"),
    ("head of", "lead"),
    ("director", "lead"),
    ("manager", "lead"),
    ("senior", "senior"),
    ("sr.", "senior"),
    ("sr ", "senior"),
    ("junior", "junior"),
    ("jr.", "junior"),
    ("jr ", "junior"),
    ("intern", "intern"),
    ("entry level", "junior"),
    ("graduate", "junior"),
]


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found = set()
    for skill in SKILL_DICT:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, lowered):
            found.add(skill)
    return sorted(found)


def guess_seniority(text: str) -> str | None:
    lowered = text.lower()
    for needle, level in SENIORITY_MAP:
        if needle in lowered:
            return level
    return None


def guess_years_experience(text: str) -> int | None:
    matches = re.findall(r"(\d+)\+?\s*(?:years|yrs|y)\s+(?:of\s+)?experience", text.lower())
    if not matches:
        return None
    try:
        return max(int(m) for m in matches)
    except Exception:
        return None


def parse_resume(file_bytes: bytes) -> dict:
    text = extract_text_from_pdf(file_bytes)
    return {
        "raw_text": text,
        "skills": extract_skills(text),
        "seniority": guess_seniority(text),
        "years_experience": guess_years_experience(text),
    }
