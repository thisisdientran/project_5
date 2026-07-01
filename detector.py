import json
import os
import re
import statistics

from labels import attribution_from_score, confidence_for_attribution, transparency_label

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - only used when dependency is missing
    def load_dotenv():
        return None


load_dotenv()

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")

AI_MARKER_PHRASES = [
    "it is important to note",
    "furthermore",
    "moreover",
    "in conclusion",
    "transformative",
    "paradigm shift",
    "stakeholders",
    "responsible deployment",
    "ethical implications",
    "various sectors",
    "delve",
    "underscore",
    "comprehensive",
]

HUMAN_MARKER_PATTERNS = [
    r"\bok\b",
    r"\bhonestly\b",
    r"\bkinda\b",
    r"\bgonna\b",
    r"\blol\b",
    r"\bmy friend\b",
    r"\bdowntown\b",
    r"\bWAY\b",
    r"\bprobably won't\b",
    r"\bi was\b",
    r"\bi'm\b",
    r"\bme\b",
]


SIGNAL_WEIGHTS = {
    "semantic_llm": 0.50,
    "stylometric": 0.35,
    "formulaic_phrases": 0.15,
}


def clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def words_for(text):
    return WORD_RE.findall(text)


def sentences_for(text):
    sentences = [item.strip() for item in SENTENCE_RE.findall(text) if item.strip()]
    return sentences or [text.strip()]


def normalize(value, low, high):
    if high == low:
        return 0.5
    return clamp((value - low) / (high - low))


def local_semantic_signal(text):
    """Offline semantic proxy used when Groq is not configured."""
    lowered = text.lower()
    words = words_for(text)
    ai_hits = sum(1 for phrase in AI_MARKER_PHRASES if phrase in lowered)
    human_hits = sum(
        1
        for pattern in HUMAN_MARKER_PATTERNS
        if re.search(pattern, text, flags=re.IGNORECASE)
    )
    first_person_count = len(re.findall(r"\b(i|me|my|mine|we|our)\b", lowered))
    contraction_count = len(re.findall(r"\b\w+'(m|re|ve|ll|d|t|s)\b", lowered))

    score = 0.52
    score += min(ai_hits * 0.095, 0.38)
    score -= min(human_hits * 0.07, 0.28)
    score -= min(first_person_count * 0.025, 0.12)
    score -= min(contraction_count * 0.035, 0.14)
    if ai_hits >= 4:
        score += 0.08

    if len(words) < 45 and ai_hits < 3:
        score = (score * 0.65) + (0.5 * 0.35)

    return {
        "name": "semantic_llm",
        "score": round(clamp(score), 3),
        "source": "local_semantic_fallback",
        "details": {
            "ai_marker_hits": ai_hits,
            "human_marker_hits": human_hits,
            "first_person_count": first_person_count,
            "contraction_count": contraction_count,
        },
        "reason": "Local proxy used because GROQ_API_KEY was not available.",
    }


def groq_semantic_signal(text):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return local_semantic_signal(text)

    try:
        from groq import Groq
    except ImportError:
        fallback = local_semantic_signal(text)
        fallback["reason"] = "Groq package was not installed; local proxy used."
        return fallback

    prompt = f"""
You are part of a provenance system for creative writing platforms.
Classify whether the submitted text reads more like human-written text or
AI-generated text. Return only JSON with:
score: number from 0.0 to 1.0 where 1.0 means very AI-like,
attribution: one of likely_ai, uncertain, likely_human,
reason: one short sentence.

Text:
\"\"\"{text[:5000]}\"\"\"
"""

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content
        parsed = json.loads(raw)
        score = clamp(float(parsed.get("score", 0.5)))
        return {
            "name": "semantic_llm",
            "score": round(score, 3),
            "source": "groq_llama_3_3_70b_versatile",
            "details": {
                "model_attribution": parsed.get("attribution", "uncertain"),
            },
            "reason": parsed.get("reason", "Groq returned a structured score."),
        }
    except Exception as exc:  # pragma: no cover - depends on external API
        fallback = local_semantic_signal(text)
        fallback["source"] = "local_fallback_after_groq_error"
        fallback["reason"] = f"Groq call failed, so local proxy was used: {exc}"
        return fallback


def stylometric_signal(text):
    sentences = sentences_for(text)
    words = words_for(text)
    word_count = len(words)

    if word_count == 0:
        return {
            "name": "stylometric",
            "score": 0.5,
            "details": {},
            "reason": "No words were available to analyze.",
        }

    sentence_lengths = [len(words_for(sentence)) for sentence in sentences]
    average_sentence_length = sum(sentence_lengths) / len(sentence_lengths)

    if len(sentence_lengths) > 1 and average_sentence_length > 0:
        sentence_stdev = statistics.pstdev(sentence_lengths)
        sentence_cv = sentence_stdev / average_sentence_length
    else:
        sentence_cv = 0.55

    unique_ratio = len({word.lower() for word in words}) / word_count

    uniformity_score = 1 - normalize(sentence_cv, 0.20, 0.90)
    low_diversity_score = 1 - normalize(unique_ratio, 0.45, 0.82)
    long_sentence_score = normalize(average_sentence_length, 12, 28)

    score = (
        0.45 * uniformity_score
        + 0.35 * low_diversity_score
        + 0.20 * long_sentence_score
    )

    if word_count < 60:
        score = (score * 0.75) + (0.5 * 0.25)

    return {
        "name": "stylometric",
        "score": round(clamp(score), 3),
        "details": {
            "word_count": word_count,
            "sentence_count": len(sentences),
            "average_sentence_length": round(average_sentence_length, 2),
            "sentence_length_cv": round(sentence_cv, 3),
            "type_token_ratio": round(unique_ratio, 3),
        },
        "reason": "Measures sentence uniformity, vocabulary diversity, and sentence length.",
    }


def formulaic_phrase_signal(text):
    lowered = text.lower()
    words = words_for(text)
    word_count = max(len(words), 1)

    phrase_hits = sum(1 for phrase in AI_MARKER_PHRASES if phrase in lowered)
    transition_hits = len(
        re.findall(
            r"\b(furthermore|moreover|additionally|therefore|however|overall)\b",
            lowered,
        )
    )
    personal_detail_hits = len(
        re.findall(
            r"\b(i|my|me|friend|mom|dad|downtown|yesterday|today|honestly|coffee|ramen)\b",
            lowered,
        )
    )

    repeated_words = 0
    seen = set()
    for word in (item.lower() for item in words if len(item) > 4):
        if word in seen:
            repeated_words += 1
        seen.add(word)

    score = 0.46
    score += min(phrase_hits * 0.12, 0.36)
    score += min(transition_hits * 0.035, 0.18)
    score += min((repeated_words / word_count) * 1.2, 0.18)
    score -= min(personal_detail_hits * 0.035, 0.18)
    if phrase_hits >= 4:
        score += 0.08

    if word_count < 45 and phrase_hits < 3:
        score = (score * 0.70) + (0.5 * 0.30)

    return {
        "name": "formulaic_phrases",
        "score": round(clamp(score), 3),
        "details": {
            "phrase_hits": phrase_hits,
            "transition_hits": transition_hits,
            "personal_detail_hits": personal_detail_hits,
            "repeated_long_words": repeated_words,
        },
        "reason": "Looks for template-like phrases, transitions, repetition, and personal detail.",
    }


def analyze_text(text):
    signals = [
        groq_semantic_signal(text),
        stylometric_signal(text),
        formulaic_phrase_signal(text),
    ]
    signal_scores = {signal["name"]: signal["score"] for signal in signals}
    ai_likelihood = sum(
        signal_scores[name] * weight for name, weight in SIGNAL_WEIGHTS.items()
    )
    ai_likelihood = round(clamp(ai_likelihood), 3)
    attribution = attribution_from_score(ai_likelihood)
    confidence = confidence_for_attribution(ai_likelihood, attribution)

    return {
        "attribution": attribution,
        "confidence": confidence,
        "ai_likelihood": ai_likelihood,
        "label": transparency_label(attribution),
        "signals": signals,
        "signal_weights": SIGNAL_WEIGHTS,
    }
