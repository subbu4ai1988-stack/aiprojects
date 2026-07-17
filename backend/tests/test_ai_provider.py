from backend.app import services
from backend.app.ai_provider import ai_status


class FakeProvider:
    def parse_resume(self, text):
        return {"name": "Ada", "email": "ada@example.com", "phone": "", "skills": ["Python"], "years_experience": 6}

    def rank_resume(self, resume, description, skills):
        return 91.5, "Strong evidence-based fit."

    def generate_questions(self, title, description):
        return [{"text": f"Question {i}", "category": "Technical", "difficulty": "Medium"} for i in range(1, 7)]

    def analyze_answers(self, answers, description):
        return "Overall score: 88/100", "select", 0.89


class FailingProvider:
    def parse_resume(self, text):
        raise RuntimeError("provider unavailable")

    def rank_resume(self, resume, description, skills):
        raise RuntimeError("provider unavailable")

    def generate_questions(self, title, description):
        raise RuntimeError("provider unavailable")

    def analyze_answers(self, answers, description):
        raise RuntimeError("provider unavailable")


def test_openai_adapter_is_used_without_changing_service_contracts(monkeypatch):
    monkeypatch.setattr(services, "get_ai_provider", lambda: FakeProvider())

    parsed = services.parse_resume("Ada resume")
    score, summary = services.rank_resume("resume", "Python role", ["Python"])
    questions = services.generate_questions("Engineer", "Python role")
    report, recommendation, confidence = services.analyze_answers([{"answer": "Evidence"}], "Python role")

    assert parsed["name"] == "Ada"
    assert parsed["raw_text"] == "Ada resume"
    assert parsed["_ai_source"] == "openai"
    assert (score, summary) == (91.5, "Strong evidence-based fit.")
    assert len(questions) == 6
    assert (report, recommendation, confidence) == ("Overall score: 88/100", "select", 0.89)


def test_provider_failure_falls_back_to_local_ai(monkeypatch):
    monkeypatch.setattr(services, "get_ai_provider", lambda: FailingProvider())

    parsed = services.parse_resume("Grace Hopper\ngrace@example.com\n10 years Python")
    score, summary = services.rank_resume("Python SQL", "Python SQL role", ["Python"])
    questions = services.generate_questions("Engineer", "Python SQL role")
    report, recommendation, confidence = services.analyze_answers([{"answer": "I used Python"}], "Python role")

    assert parsed["_ai_source"] == "local"
    assert score > 0 and "Matched strengths" in summary
    assert len(questions) == 6
    assert "Overall score" in report
    assert recommendation in {"select", "consider", "reject"}
    assert 0 <= confidence <= 1


def test_ai_status_never_exposes_credentials(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    status = ai_status()

    assert status["requested_provider"] == "openai"
    assert status["active_provider"] == "local"
    assert status["configured"] is False
    assert "api_key" not in status
