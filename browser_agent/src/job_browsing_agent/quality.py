from job_browsing_agent.models import ExtractedJobCandidate


def assess(candidate: ExtractedJobCandidate) -> ExtractedJobCandidate:
    reasons: list[str] = []
    if candidate.company == "未说明":
        reasons.append("missing_company")
    if candidate.city == "未说明":
        reasons.append("missing_city")
    if len(candidate.description) < 80:
        reasons.append("short_description")
    if candidate.requirements.startswith("未单独说明"):
        reasons.append("missing_requirements")
    if reasons:
        candidate.confidence = min(candidate.confidence, 0.69)
    candidate.review_reasons = reasons
    return candidate


def needs_review(candidate: ExtractedJobCandidate) -> bool:
    return candidate.confidence < 0.75 or bool(candidate.review_reasons)
