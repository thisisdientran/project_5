# Provenance Guard

Provenance Guard is a small Flask backend that a creative writing platform could use to add attribution context to submitted text. It accepts a writing sample, runs multiple detection signals, returns an attribution result with confidence, shows a reader-facing transparency label, logs the decision, and lets the creator appeal.

## Running the Project

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add a Groq key to `.env` if you want the semantic signal to call Groq:

```bash
GROQ_API_KEY=your_key_here
```

Then start the API:

```bash
python app.py
```

The local API runs at `http://127.0.0.1:5000`.

## Architecture Overview

A submitted text moves through this path:

`POST /submit` receives `text` and `creator_id`, validates the request, runs the detection pipeline, combines the signal scores into one `ai_likelihood`, maps that score to an attribution and transparency label, stores the content record, writes a structured audit-log entry, and returns JSON to the platform.

Appeals use a separate path:

`POST /appeal` receives `content_id` and `creator_reasoning`, finds the original decision, updates the content status to `under_review`, stores the appeal, writes an appeal event to the audit log, and returns a confirmation.

The full architecture diagram is in [planning.md](planning.md).

## API Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/submit` | POST | Analyze text and return attribution, confidence, label, and signal scores |
| `/appeal` | POST | Put a contested classification under review |
| `/log` | GET | Return recent audit-log entries |
| `/analytics` | GET | Return simple detection counts, appeal rate, and average AI-likelihood |
| `/health` | GET | Confirm the service is running |

Example submission:

```bash
curl -s -X POST http://127.0.0.1:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon, painting the sky in amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.", "creator_id": "test-user-1"}' | python -m json.tool
```

## Detection Signals

This project uses three signals, so it also covers the ensemble detection stretch feature.

| Signal | What it measures | Why I chose it | What it misses |
| --- | --- | --- | --- |
| Semantic LLM signal | A holistic judgment of whether the writing reads human or AI-generated | It can notice overall tone, generic wording, and context better than simple rules | It can be biased against polished formal human writing |
| Stylometric heuristic signal | Sentence length variation, vocabulary diversity, and average sentence length | It is transparent and does not depend on an external model | Short texts, poems, and formal writing can confuse it |
| Formulaic phrase signal | Template-like AI phrases, transitions, repeated long words, and personal details | It catches common generated-writing patterns without letting them dominate | Humans also use formulaic phrases in essays and business writing |

The semantic signal uses Groq with `llama-3.3-70b-versatile` when `GROQ_API_KEY` is configured. If no key is present, the app uses a local fallback so the project can still run during grading or offline demos.

## Confidence Scoring

Each signal returns an AI-likelihood score from `0.0` to `1.0`. Higher means more AI-like. The combined score uses this weighting:

| Signal | Weight |
| --- | ---: |
| Semantic LLM signal | 0.50 |
| Stylometric heuristic signal | 0.35 |
| Formulaic phrase signal | 0.15 |

The thresholds are intentionally conservative:

| AI-likelihood | Attribution |
| --- | --- |
| `0.72` to `1.00` | `likely_ai` |
| `0.29` to `0.71` | `uncertain` |
| `0.00` to `0.28` | `likely_human` |

I kept the uncertain range wide because a false positive is worse than a false negative on a writing platform. A `0.60` AI-likelihood means the system leans AI but should not label the piece AI-generated. A `0.95` means the signals strongly agree.

Two example scores from local testing:

| Example | Attribution | Confidence | AI-likelihood | Signal scores |
| --- | --- | ---: | ---: | --- |
| Formal AI-like sample | `likely_ai` | `0.770` | `0.770` | semantic `0.980`, stylometric `0.398`, phrase `0.935` |
| Casual personal ramen review | `likely_human` | `0.813` | `0.187` | semantic `0.105`, stylometric `0.264`, phrase `0.280` |
| Formal borderline policy paragraph | `uncertain` | `0.517` | `0.517` | semantic `0.513`, stylometric `0.525`, phrase `0.511` |

These examples show that the scores are not constant: the obvious AI-like text, casual human text, and formal borderline text land in different regions.

## Transparency Labels

The exact label text returned by `/submit` is:

| Variant | Exact text |
| --- | --- |
| High-confidence AI | "AI-use disclosure: This piece was classified as likely AI-generated with high confidence. The creator can appeal if this does not reflect their process." |
| High-confidence human | "Human-authorship signal: This piece was classified as likely human-written with high confidence. This is context for readers, not proof of authorship." |
| Uncertain | "Authorship unclear: The system found mixed signals and cannot confidently classify this piece. Readers should treat the attribution as unresolved." |

## Appeals Workflow

A creator can appeal by sending the content ID and their reasoning:

```bash
curl -s -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "d098d3a4-0c43-43f9-8d7d-76a4bd853eea", "creator_reasoning": "I wrote this myself from class notes and want a human reviewer to check the context."}' | python -m json.tool
```

The app updates the content status to `under_review`, stores the reasoning, and writes an appeal entry to the audit log with the original decision attached.

Example response:

```json
{
  "content_id": "d098d3a4-0c43-43f9-8d7d-76a4bd853eea",
  "status": "under_review",
  "message": "Appeal received and queued for human review."
}
```

## Rate Limiting

`POST /submit` is limited to:

```text
10 per minute;100 per day
```

I chose these limits because a normal creator may test a few drafts quickly, but 10 per minute blocks simple spam scripts. The 100-per-day limit is high enough for an active creator and low enough to reduce abuse in a class-project backend.

Rate-limit test result from local testing:

```text
200 200 200 200 200 200 200 200 200 200 429 429
```

The project is configured to use Flask-Limiter with `memory://` storage. If Flask-Limiter is not installed, `app.py` includes a small local fallback limiter so the endpoint still behaves correctly during a quick demo.

## Audit Log

Audit data is stored as structured JSON in [data/audit_log.json](data/audit_log.json). `GET /log` returns the most recent entries:

```bash
curl -s http://127.0.0.1:5000/log?limit=4 | python -m json.tool
```

Sample entries:

```json
[
  {
    "event_type": "classification",
    "content_id": "d098d3a4-0c43-43f9-8d7d-76a4bd853eea",
    "creator_id": "test-user-ai",
    "attribution": "likely_ai",
    "confidence": 0.77,
    "ai_likelihood": 0.77,
    "signal_scores": {
      "semantic_llm": 0.98,
      "stylometric": 0.398,
      "formulaic_phrases": 0.935
    },
    "status": "classified"
  },
  {
    "event_type": "classification",
    "content_id": "30d703c0-a1db-4d00-80e8-3f621c912065",
    "creator_id": "test-user-human",
    "attribution": "likely_human",
    "confidence": 0.813,
    "ai_likelihood": 0.187,
    "signal_scores": {
      "semantic_llm": 0.105,
      "stylometric": 0.264,
      "formulaic_phrases": 0.28
    },
    "status": "classified"
  },
  {
    "event_type": "classification",
    "content_id": "76091cf7-0356-4741-b077-328a74dc7438",
    "creator_id": "test-user-borderline",
    "attribution": "uncertain",
    "confidence": 0.517,
    "ai_likelihood": 0.517,
    "signal_scores": {
      "semantic_llm": 0.513,
      "stylometric": 0.525,
      "formulaic_phrases": 0.511
    },
    "status": "classified"
  },
  {
    "event_type": "appeal",
    "content_id": "d098d3a4-0c43-43f9-8d7d-76a4bd853eea",
    "creator_id": "test-user-ai",
    "appeal_reasoning": "I wrote this myself from class notes and want a human reviewer to check the context.",
    "status": "under_review"
  }
]
```

The full stored log also includes timestamps, text hashes, signal details, and original decisions for appeals.

## Analytics Dashboard Stretch

I added a small JSON analytics view at `/analytics`. It returns:

```json
{
  "classification_count": 3,
  "appeal_count": 1,
  "appeal_rate": 0.333,
  "attribution_counts": {
    "likely_ai": 1,
    "likely_human": 1,
    "uncertain": 1
  },
  "average_ai_likelihood": 0.491
}
```

This is not a visual dashboard, but it gives a platform the basic metrics needed to build one.

## Known Limitations

Poetry with repetition may be misclassified because the stylometric and formulaic signals treat repetition as suspicious. A poem that repeats a simple phrase for effect could look AI-generated even when it is fully human.

Formal student essays are another weak spot. A careful human writer may use balanced sentences and transitions like "therefore" or "moreover," which can push the score upward.

Short submissions are also unreliable because sentence variation and vocabulary diversity need enough text to measure.

## Spec Reflection

Writing `planning.md` first helped because the labels, thresholds, and appeal behavior were already decided before coding. That made the Flask routes mostly a matter of matching the plan instead of inventing behavior while implementing.

One thing that changed during implementation was the local fallback for the semantic signal. The spec expects Groq as the main semantic classifier, but I added a fallback so the project can still be tested without an API key or network access. I kept the fallback explicit in the audit log through `signal_sources`.

## AI Usage

1. I directed the AI tool to turn the architecture plan into a Flask project structure with separate modules for the app routes, detector logic, labels, and storage. I revised the output to keep the storage simple JSON instead of adding a database, because JSON is easier to inspect for this project.
2. I used AI help to calibrate the local scoring examples against the thresholds in `planning.md`. I checked the results manually and adjusted the fallback so obvious AI-like text, casual human text, and borderline formal text landed in different label regions.
3. I used AI to draft the README sections, then edited them to include the exact label text, real sample scores, rate-limit evidence, and the specific limitations tied to my signals.

## Walkthrough Notes

For the portfolio walkthrough, I would show:

1. `planning.md`, especially the architecture diagram and thresholds.
2. A `/submit` call that returns `likely_ai`.
3. A second `/submit` call that returns `likely_human` or `uncertain`.
4. A `/appeal` call using the first content ID.
5. `/log?limit=4` showing three classifications and one appeal.
6. The rate-limit test output with the final two requests returning `429`.
# project_5
