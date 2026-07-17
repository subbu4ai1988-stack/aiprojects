import json
from pathlib import Path

from backend.app.services import _local_rank_resume


def main() -> None:
    cases = json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))
    failures = []
    for case in cases:
        strong, _ = _local_rank_resume(case["strong_resume"], case["job_description"], case["required_skills"])
        weak, _ = _local_rank_resume(case["weak_resume"], case["job_description"], case["required_skills"])
        print(f"{case['name']}: strong={strong}, weak={weak}")
        if strong <= weak:
            failures.append(case["name"])
    if failures:
        raise SystemExit(f"Ranking evaluation failed: {', '.join(failures)}")
    print(f"Local ranking evaluation passed: {len(cases)} cases")


if __name__ == "__main__":
    main()
