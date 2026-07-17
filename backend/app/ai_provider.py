import math
import os
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()


class ResumeProfile(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    skills: list[str]
    years_experience: int = Field(ge=0)
    education: list[str]
    experience_summary: str


class MatchAssessment(BaseModel):
    match_score: float = Field(ge=0, le=100)
    strengths: list[str]
    gaps: list[str]
    summary: str


class InterviewQuestion(BaseModel):
    text: str
    category: Literal["Technical", "Behavioral", "Situational"]
    difficulty: Literal["Simple", "Medium", "Complex"]


class QuestionSet(BaseModel):
    questions: list[InterviewQuestion] = Field(min_length=6, max_length=6)


class QuestionFeedback(BaseModel):
    question_number: int = Field(ge=1)
    score: int = Field(ge=0, le=100)
    feedback: str


class InterviewAssessment(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    recommendation: Literal["select", "consider", "reject"]
    confidence: float = Field(ge=0, le=1)
    question_feedback: list[QuestionFeedback]
    summary: str


class OpenAIProvider:
    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
        self.embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "45")),
            max_retries=2,
        )
        self._usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_id": ""}

    def _reset_usage(self) -> None:
        self._usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_id": ""}

    def _capture_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage:
            input_tokens = int(getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", 0)) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
            self._usage["input_tokens"] += input_tokens
            self._usage["output_tokens"] += output_tokens
            self._usage["total_tokens"] += total_tokens
        request_id = getattr(response, "_request_id", "")
        if request_id:
            self._usage["request_id"] = request_id

    def usage_snapshot(self) -> dict:
        return dict(self._usage)

    def _parse(self, schema: type[BaseModel], system: str, user: str) -> BaseModel:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text_format=schema,
        )
        self._capture_usage(response)
        if response.output_parsed is None:
            raise RuntimeError("OpenAI response did not contain structured output")
        return response.output_parsed

    def parse_resume(self, text: str) -> dict:
        self._reset_usage()
        profile = self._parse(
            ResumeProfile,
            "Extract a factual candidate profile from the supplied resume. Do not infer credentials that are not present.",
            text[:30000],
        )
        return profile.model_dump()

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
        return numerator / denominator if denominator else 0.0

    def rank_resume(self, resume_text: str, job_description: str, required_skills: list[str]) -> tuple[float, str]:
        self._reset_usage()
        job_context = f"Job description:\n{job_description}\nRequired skills: {', '.join(required_skills)}"
        embedding_response = self.client.embeddings.create(
            model=self.embedding_model,
            input=[job_context[:30000], resume_text[:30000]],
        )
        self._capture_usage(embedding_response)
        vectors = embedding_response.data
        semantic_score = max(0.0, min(100.0, (self._cosine(vectors[0].embedding, vectors[1].embedding) + 1) * 50))
        assessment = self._parse(
            MatchAssessment,
            "Assess job fit only from evidence in the resume. Treat required skills as important and clearly identify missing evidence.",
            f"{job_context}\n\nResume:\n{resume_text[:30000]}",
        )
        score = round(assessment.match_score * 0.6 + semantic_score * 0.4, 1)
        strengths = ", ".join(assessment.strengths[:5]) or "No specific strengths identified"
        gaps = ", ".join(assessment.gaps[:5]) or "No material gaps identified"
        return score, f"{assessment.summary} Strengths: {strengths}. Gaps: {gaps}."

    def generate_questions(self, title: str, description: str) -> list[dict]:
        self._reset_usage()
        result = self._parse(
            QuestionSet,
            "Create exactly six concise, job-relevant interview questions with a balanced mix of technical, behavioral, and situational categories and increasing difficulty.",
            f"Role: {title}\nJob description:\n{description[:20000]}",
        )
        return [question.model_dump() for question in result.questions]

    def analyze_answers(self, answers: list[dict], description: str) -> tuple[str, str, float]:
        self._reset_usage()
        formatted = "\n\n".join(
            f"Question {index}: {item.get('question', '')}\nAnswer: {item.get('answer', '') or '[No text answer supplied]'}"
            for index, item in enumerate(answers, 1)
        )
        result = self._parse(
            InterviewAssessment,
            "Evaluate the interview answers consistently against the role. Base scores on relevance, evidence, clarity, and role competency. Do not invent information.",
            f"Job description:\n{description[:16000]}\n\nInterview:\n{formatted[:30000]}",
        )
        lines = [
            f"Q{item.question_number}: {item.score}/100 - {item.feedback}"
            for item in result.question_feedback
        ]
        lines.extend([f"Overall score: {result.overall_score}/100", f"Summary: {result.summary}"])
        return "\n".join(lines), result.recommendation, round(result.confidence, 2)


def get_ai_provider() -> OpenAIProvider | None:
    if os.getenv("AI_PROVIDER", "local").strip().lower() != "openai":
        return None
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return OpenAIProvider()


def ai_status() -> dict:
    requested = os.getenv("AI_PROVIDER", "local").strip().lower()
    configured = requested == "openai" and bool(os.getenv("OPENAI_API_KEY"))
    return {
        "requested_provider": requested,
        "active_provider": "openai" if configured else "local",
        "configured": configured,
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "automatic_fallback": True,
    }
