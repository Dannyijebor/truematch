"""Job family detection + family-specific skill vocabularies.

The old scorer was 100% tech. This lets a nurse, salesperson, teacher,
or accountant get matched against jobs in their own field.
"""

FAMILIES = {
    "software": {
        "display": "Software Engineering",
        "title_kw": ["engineer", "developer", "programmer", "swe", "frontend", "backend", "full stack", "fullstack", "devops", "sre", "platform", "mobile", "ios", "android", "qa", "test engineer"],
        "skills": ["python", "javascript", "typescript", "java", "go", "golang", "rust", "ruby", "php", "c++", "c#", "kotlin", "swift", "scala", "react", "vue", "angular", "next.js", "node", "express", "fastapi", "django", "flask", "rails", "spring", "graphql", "rest", "postgresql", "mysql", "mongodb", "redis", "docker", "kubernetes", "aws", "gcp", "azure", "terraform", "git", "linux", "ci/cd", "microservices"],
    },
    "data": {
        "display": "Data & Analytics",
        "title_kw": ["data scientist", "data analyst", "data engineer", "analytics", "machine learning", "ml engineer", "ai engineer", "bi ", "business intelligence", "statistician"],
        "skills": ["python", "r", "sql", "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "spark", "hadoop", "airflow", "dbt", "snowflake", "bigquery", "redshift", "tableau", "power bi", "looker", "excel", "statistics", "a/b testing", "etl"],
    },
    "design": {
        "display": "Design",
        "title_kw": ["designer", "ux", "ui ", "product design", "graphic design", "visual design", "brand design", "illustrator"],
        "skills": ["figma", "sketch", "adobe xd", "photoshop", "illustrator", "indesign", "after effects", "prototyping", "wireframing", "user research", "design systems", "typography", "branding", "motion design"],
    },
    "product": {
        "display": "Product Management",
        "title_kw": ["product manager", "product owner", "pm ", "product lead", "technical product"],
        "skills": ["roadmap", "user stories", "agile", "scrum", "jira", "confluence", "okrs", "a/b testing", "analytics", "stakeholder management", "product strategy", "go-to-market"],
    },
    "marketing": {
        "display": "Marketing",
        "title_kw": ["marketing", "growth", "seo", "content", "social media", "brand manager", "demand gen", "performance marketing", "copywriter"],
        "skills": ["seo", "sem", "google ads", "facebook ads", "meta ads", "content marketing", "email marketing", "hubspot", "mailchimp", "copywriting", "social media", "google analytics", "ga4", "crm", "marketo", "brand strategy"],
    },
    "sales": {
        "display": "Sales",
        "title_kw": ["sales", "account executive", "sdr", "bdr", "business development", "account manager", "sales manager", "sales rep"],
        "skills": ["salesforce", "hubspot", "crm", "cold calling", "cold outreach", "pipeline management", "quota", "negotiation", "b2b sales", "saas sales", "account management", "lead generation", "prospecting"],
    },
    "customer_success": {
        "display": "Customer Success & Support",
        "title_kw": ["customer success", "customer support", "customer service", "support engineer", "help desk", "call center", "client success"],
        "skills": ["zendesk", "intercom", "freshdesk", "salesforce", "crm", "ticketing", "sla", "onboarding", "account management", "customer retention", "churn reduction", "escalation"],
    },
    "operations": {
        "display": "Operations",
        "title_kw": ["operations", "ops manager", "chief of staff", "business operations", "revops", "supply chain", "logistics", "warehouse"],
        "skills": ["process improvement", "lean", "six sigma", "excel", "sql", "supply chain", "logistics", "inventory", "erp", "sap", "oracle", "vendor management", "kpi", "sop"],
    },
    "finance": {
        "display": "Finance",
        "title_kw": ["finance", "financial analyst", "fp&a", "investment", "banking", "treasury", "controller", "cfo", "private equity", "venture capital"],
        "skills": ["financial modeling", "excel", "valuation", "dcf", "lbo", "budgeting", "forecasting", "variance analysis", "ifrs", "gaap", "bloomberg", "capital iq", "quickbooks", "netsuite"],
    },
    "accounting": {
        "display": "Accounting",
        "title_kw": ["accountant", "accounting", "audit", "tax", "bookkeeper", "payroll"],
        "skills": ["quickbooks", "xero", "netsuite", "sage", "excel", "ifrs", "gaap", "tax preparation", "audit", "reconciliation", "accounts payable", "accounts receivable", "payroll", "vat"],
    },
    "hr": {
        "display": "Human Resources",
        "title_kw": ["hr ", "human resources", "recruiter", "talent", "people ops", "people partner", "compensation", "benefits"],
        "skills": ["recruiting", "ats", "greenhouse", "lever", "workday", "onboarding", "employee relations", "compensation", "benefits", "hris", "performance management", "hris"],
    },
    "legal": {
        "display": "Legal",
        "title_kw": ["lawyer", "attorney", "legal counsel", "paralegal", "compliance", "contract manager"],
        "skills": ["contract drafting", "litigation", "compliance", "gdpr", "corporate law", "intellectual property", "due diligence", "legal research", "regulatory"],
    },
    "healthcare": {
        "display": "Healthcare",
        "title_kw": ["nurse", "doctor", "physician", "clinician", "medical", "clinical", "pharmacist", "therapist", "surgeon", "midwife", "caregiver", "health"],
        "skills": ["patient care", "triage", "ehr", "epic", "cerner", "cpr", "bls", "acls", "iv therapy", "vital signs", "medication administration", "clinical assessment", "hipaa", "phlebotomy", "wound care", "icu", "emergency", "pediatrics", "oncology"],
    },
    "education": {
        "display": "Education",
        "title_kw": ["teacher", "instructor", "professor", "tutor", "lecturer", "educator", "curriculum"],
        "skills": ["lesson planning", "curriculum design", "classroom management", "student assessment", "differentiated instruction", "iep", "common core", "google classroom", "canvas lms", "moodle", "pedagogy", "stem"],
    },
    "hospitality": {
        "display": "Hospitality & Tourism",
        "title_kw": ["hotel", "restaurant", "chef", "cook", "waiter", "barista", "hospitality", "tourism", "front desk", "concierge"],
        "skills": ["guest services", "food safety", "haccp", "menu planning", "pos system", "reservations", "housekeeping", "bartending", "customer service", "upselling", "food handler"],
    },
    "retail": {
        "display": "Retail",
        "title_kw": ["retail", "store manager", "cashier", "sales associate", "merchandiser", "buyer"],
        "skills": ["pos", "inventory", "merchandising", "customer service", "visual merchandising", "loss prevention", "sales targets", "stock management", "cash handling"],
    },
    "logistics": {
        "display": "Logistics & Transport",
        "title_kw": ["driver", "logistics", "supply chain", "warehouse", "fleet", "dispatcher", "courier", "delivery"],
        "skills": ["cdl", "forklift", "route planning", "inventory management", "warehouse management", "wms", "fleet management", "dispatch", "supply chain", "customs"],
    },
    "engineering_hardware": {
        "display": "Hardware Engineering",
        "title_kw": ["mechanical engineer", "electrical engineer", "civil engineer", "hardware engineer", "embedded", "firmware", "manufacturing engineer"],
        "skills": ["cad", "solidworks", "autocad", "matlab", "embedded c", "rtos", "pcb design", "verilog", "vhdl", "fpga", "gd&t", "ansys", "mechanical design", "electrical systems"],
    },
    "biotech": {
        "display": "Biotech & Pharma",
        "title_kw": ["biotech", "pharma", "research scientist", "biologist", "chemist", "lab", "clinical research", "bioinformatics"],
        "skills": ["pcr", "elisa", "cell culture", "hplc", "gc-ms", "bioinformatics", "clinical trials", "gmp", "fda", "assay development", "molecular biology", "protein purification"],
    },
    "manufacturing": {
        "display": "Manufacturing",
        "title_kw": ["manufacturing", "production", "assembly", "plant manager", "quality engineer", "process engineer"],
        "skills": ["lean manufacturing", "six sigma", "kaizen", "5s", "iso 9001", "root cause analysis", "spc", "cad", "cnc", "plc", "scada", "quality control"],
    },
    "construction": {
        "display": "Construction",
        "title_kw": ["construction", "site manager", "project engineer", "foreman", "architect", "surveyor"],
        "skills": ["autocad", "revit", "bim", "project scheduling", "cost estimation", "osha", "site supervision", "concrete", "structural", "quantity surveying", "primavera"],
    },
    "nonprofit": {
        "display": "Nonprofit & NGO",
        "title_kw": ["nonprofit", "ngo", "program manager", "development officer", "grant", "advocacy", "humanitarian"],
        "skills": ["grant writing", "fundraising", "program management", "monitoring and evaluation", "m&e", "stakeholder engagement", "advocacy", "community outreach", "donor relations", "logframe"],
    },
    "government": {
        "display": "Government & Public Sector",
        "title_kw": ["government", "public sector", "policy", "civil service", "municipal", "federal", "state agency"],
        "skills": ["policy analysis", "public administration", "regulatory", "procurement", "grant management", "stakeholder engagement", "legislative", "budget analysis"],
    },
    "admin": {
        "display": "Admin & Office",
        "title_kw": ["administrative", "executive assistant", "office manager", "receptionist", "secretary", "coordinator"],
        "skills": ["microsoft office", "excel", "outlook", "calendar management", "travel coordination", "expense reports", "scheduling", "data entry", "customer service", "event planning"],
    },
    "other": {
        "display": "Other",
        "title_kw": [],
        "skills": [],
    },
}


def detect_family(title: str, description: str = "") -> str:
    """Return the most likely job family, or 'other'."""
    text = ((title or "") + " " + (description or "")[:800]).lower()

    # Priority order: healthcare, education, legal first (highest-stakes classification).
    order = ["healthcare", "education", "legal", "software", "data", "design", "product",
             "marketing", "sales", "customer_success", "operations", "finance",
             "accounting", "hr", "hospitality", "retail", "logistics",
             "engineering_hardware", "biotech", "manufacturing", "construction",
             "nonprofit", "government", "admin"]

    # Strong title match first
    title_l = (title or "").lower()
    for family in order:
        for kw in FAMILIES[family]["title_kw"]:
            if kw in title_l:
                return family

    # Then weaker description match — score-based, needs >= 2 hits
    scores = {}
    for family in order:
        hits = sum(1 for kw in FAMILIES[family]["title_kw"] if kw in text)
        if hits:
            scores[family] = hits
    if scores:
        best, best_n = max(scores.items(), key=lambda kv: kv[1])
        if best_n >= 2:
            return best

    return "other"


def family_skills(family: str) -> list[str]:
    """Return the skill vocabulary for a family (falls back to software if unknown)."""
    return FAMILIES.get(family, FAMILIES["other"])["skills"]


def family_display(family: str) -> str:
    return FAMILIES.get(family, FAMILIES["other"])["display"]


def all_families() -> list[str]:
    return list(FAMILIES.keys())
