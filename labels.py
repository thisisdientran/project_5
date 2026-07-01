LIKELY_AI_THRESHOLD = 0.72
LIKELY_HUMAN_THRESHOLD = 0.28

LABEL_TEXT = {
    "likely_ai": (
        "AI-use disclosure: This piece was classified as likely AI-generated "
        "with high confidence. The creator can appeal if this does not reflect "
        "their process."
    ),
    "likely_human": (
        "Human-authorship signal: This piece was classified as likely "
        "human-written with high confidence. This is context for readers, not "
        "proof of authorship."
    ),
    "uncertain": (
        "Authorship unclear: The system found mixed signals and cannot "
        "confidently classify this piece. Readers should treat the attribution "
        "as unresolved."
    ),
}


def attribution_from_score(ai_likelihood):
    """Map directional AI-likelihood to the displayed attribution result."""
    if ai_likelihood >= LIKELY_AI_THRESHOLD:
        return "likely_ai"
    if ai_likelihood <= LIKELY_HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def confidence_for_attribution(ai_likelihood, attribution):
    """Return confidence in the displayed attribution, not just AI likelihood."""
    if attribution == "likely_ai":
        return round(ai_likelihood, 3)
    if attribution == "likely_human":
        return round(1 - ai_likelihood, 3)
    return round(max(ai_likelihood, 1 - ai_likelihood), 3)


def transparency_label(attribution):
    return LABEL_TEXT[attribution]
