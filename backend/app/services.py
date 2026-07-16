import re
from collections import Counter
from pathlib import Path

from docx import Document
from pypdf import PdfReader

STOP = {"and", "the", "with", "for", "that", "from", "this", "have", "will", "your", "you", "our", "are", "job", "role"}


def extract_resume(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if path.suffix.lower() == ".docx":
        return "\n".join(p.text for p in Document(path).paragraphs)
    raise ValueError("Only PDF and DOCX resumes are supported")


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z+#.]{2,}", text.lower()) if w not in STOP}


def parse_resume(text: str) -> dict:
    email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skill_counts = Counter(re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", text.lower()))
    skills = [word for word, _ in skill_counts.most_common(20) if word not in STOP]
    years = [int(x) for x in re.findall(r"(\d{1,2})\+?\s+years?", text.lower())]
    return {"name": lines[0][:160] if lines else "Unknown Candidate", "email": email.group(0) if email else "", "phone": phone.group(0) if phone else "", "skills": skills[:12], "years_experience": max(years, default=0), "raw_text": text[:20000]}


def rank_resume(resume_text: str, job_description: str, required_skills: list[str]) -> tuple[float, str]:
    job_terms = keywords(job_description) | {s.lower() for s in required_skills}
    resume_terms = keywords(resume_text)
    matched = sorted(job_terms & resume_terms)
    missing = sorted(job_terms - resume_terms)
    score = round(100 * len(matched) / max(len(job_terms), 1), 1)
    summary = f"Matched strengths: {', '.join(matched[:10]) or 'general experience'}."
    if missing:
        summary += f" Review gaps: {', '.join(missing[:6])}."
    return score, summary


def generate_questions(title: str, description: str) -> list[dict]:
    focus = sorted(keywords(description))[:4]
    topic = ", ".join(focus) or title
    return [
        {"difficulty": "Simple", "category": "Behavioral", "text": f"Tell us about your experience relevant to {title}."},
        {"difficulty": "Simple", "category": "Technical", "text": f"How have you used {focus[0] if focus else title} in your work?"},
        {"difficulty": "Medium", "category": "Situational", "text": f"Describe how you would solve a practical problem involving {topic}."},
        {"difficulty": "Medium", "category": "Behavioral", "text": "Describe a difficult project, your contribution, and its measurable result."},
        {"difficulty": "Complex", "category": "Technical", "text": f"Design a scalable approach for the most challenging responsibility in this {title} role."},
        {"difficulty": "Complex", "category": "Situational", "text": "How would you handle conflicting priorities while maintaining quality and stakeholder trust?"},
    ]


def analyze_answers(answers: list[dict], description: str) -> tuple[str, str, float]:
    target = keywords(description)
    sections, scores = [], []
    for index, item in enumerate(answers, 1):
        answer = item.get("answer", "")
        overlap = len(keywords(answer) & target)
        clarity = min(len(answer.split()) / 80, 1)
        score = min(100, round(35 + overlap * 8 + clarity * 30))
        scores.append(score)
        sections.append(f"Q{index}: {score}/100 - {'Strong' if score >= 70 else 'Developing'} relevance and clarity.")
    overall = round(sum(scores) / max(len(scores), 1))
    recommendation = "select" if overall >= 75 else "consider" if overall >= 55 else "reject"
    confidence = round(min(0.95, 0.55 + len(answers) * 0.05), 2)
    return "\n".join(sections + [f"Overall score: {overall}/100"]), recommendation, confidence

