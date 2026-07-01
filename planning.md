# Provenance Guard Planning

## Project Goal

Provenance Guard is a backend service for a creative writing platform. A creator submits text, the service checks multiple signals, returns an attribution result with a confidence score, shows a transparency label, and lets the creator appeal the decision if they think it is wrong.

I am designing the system to be cautious about false positives. Calling a human writer's work AI-generated can damage trust, so the system only uses the high-confidence AI label when the combined AI-likelihood score is clearly above the uncertain range.

## Architecture

```text
Submission flow

POST /submit
  |
  | raw text + creator_id
  v
Input validation
  |
  | cleaned text
  v
Detection pipeline
  |---- semantic LLM signal ----------> ai-likelihood score
  |---- stylometric heuristic signal -> ai-likelihood score
  |---- formulaic phrase signal ------> ai-likelihood score
  |
  | individual signal scores
  v
Confidence scoring
  |
  | combined ai_likelihood + confidence + attribution
  v
Transparency label
  |
  | label text for likely_ai, likely_human, or uncertain
  v
Audit log + content store
  |
  | structured classification entry
  v
JSON response to platform


Appeal flow

POST /appeal
  |
  | content_id + creator_reasoning
  v
Find original content record
  |
  | original decision + appeal text
  v
Update status to "under_review"
  |
  | appeal event
  v
Audit log
  |
  | confirmation
  v
JSON response to creator/platform
```

The submission flow starts with a platform sending text and a creator ID to `POST /submit`. The API validates the request, runs three independent signals, combines them into one score, maps that score to a transparency label, saves the content decision, writes a structured audit entry, and returns the result. The appeal flow starts with `POST /appeal`, updates the original content status to `under_review`, and writes the appeal reasoning into the audit log.

## API Surface

| Endpoint | Method | Purpose | Required fields |
| --- | --- | --- | --- |
| `/submit` | POST | Analyze text and return attribution result | `text`, `creator_id` |
| `/appeal` | POST | Contest a classification | `content_id`, `creator_reasoning` |
| `/log` | GET | Show recent structured audit entries | optional `limit` |
| `/analytics` | GET | Show simple detection and appeal metrics | none |
| `/health` | GET | Confirm the API is running | none |

## Detection Signals

### Signal 1: Semantic LLM signal

This signal asks an LLM through Groq to judge whether the text reads more like human writing or AI-generated writing. It captures holistic features that are hard to encode manually, such as whether the text feels generic, overly balanced, or grounded in personal experience. The output is an AI-likelihood score from `0.0` to `1.0`, where higher means more AI-like.

Blind spot: an LLM can be biased by topic, register, and polish. A careful formal essay by a human may look AI-like, while edited AI output with personal details may look human.

Implementation note: if `GROQ_API_KEY` is not available locally, the project falls back to a small local semantic proxy so the API can still be tested without network access. The real intended path is Groq.

### Signal 2: Stylometric heuristic signal

This signal measures structural features: sentence length variation, vocabulary diversity, and average sentence length. AI text often has more even sentence structure and a polished rhythm, while casual human writing often has more uneven sentence lengths and idiosyncratic vocabulary. The output is an AI-likelihood score from `0.0` to `1.0`.

Blind spot: poems, formal academic writing, and short posts can break these assumptions. A poem may intentionally repeat simple words, and a short sample may not contain enough structure to score reliably.

### Signal 3: Formulaic phrase signal

This stretch signal looks for template-like phrases and discourse markers that often appear in AI writing, such as "it is important to note" or "furthermore." It also lowers the score for specific first-person details and informal markers. The output is an AI-likelihood score from `0.0` to `1.0`.

Blind spot: humans use formulaic phrases too, especially in school essays and business writing. This signal should influence the result, but not dominate it.

## Combining Signals

The combined `ai_likelihood` score uses weighted averaging:

| Signal | Weight |
| --- | ---: |
| Semantic LLM signal | 0.50 |
| Stylometric heuristic signal | 0.35 |
| Formulaic phrase signal | 0.15 |

I gave the semantic signal the highest weight because it can read the whole passage in context. The stylometric signal is still important because it is transparent and does not rely on an outside model. The formulaic phrase signal has the smallest weight because phrase matching is useful evidence but easy to overfit.

## Uncertainty Representation

The combined score means:

| `ai_likelihood` range | Attribution |
| --- | --- |
| `0.72` to `1.00` | `likely_ai` |
| `0.29` to `0.71` | `uncertain` |
| `0.00` to `0.28` | `likely_human` |

A score near `0.50` means the signals are mixed or weak. A score of `0.60` does not mean "60 percent proven AI"; it means the system leans AI but not strongly enough to label it that way. A score of `0.95` means the signals strongly agree that the text looks AI-generated.

The response includes two related numbers:

| Field | Meaning |
| --- | --- |
| `ai_likelihood` | Directional score from human-like `0.0` to AI-like `1.0` |
| `confidence` | Confidence in the displayed attribution label |

For `likely_ai`, confidence equals `ai_likelihood`. For `likely_human`, confidence equals `1 - ai_likelihood`. For `uncertain`, confidence is low because neither side is strong.

## Transparency Label Design

Exact label variants:

| Variant | Exact text |
| --- | --- |
| High-confidence AI | "AI-use disclosure: This piece was classified as likely AI-generated with high confidence. The creator can appeal if this does not reflect their process." |
| High-confidence human | "Human-authorship signal: This piece was classified as likely human-written with high confidence. This is context for readers, not proof of authorship." |
| Uncertain | "Authorship unclear: The system found mixed signals and cannot confidently classify this piece. Readers should treat the attribution as unresolved." |

## Appeals Workflow

Any creator who receives a classification can submit an appeal by sending the `content_id` and `creator_reasoning` to `POST /appeal`. The reasoning should explain why the creator believes the classification is wrong or what context the system missed.

When an appeal is received, the system:

1. Finds the original content record by `content_id`.
2. Updates the content status from `classified` to `under_review`.
3. Saves the appeal reasoning with a timestamp.
4. Writes a structured audit-log entry that links the appeal to the original decision.
5. Returns a confirmation response.

A human reviewer opening the appeal queue would need the original classification, signal scores, confidence, creator ID, text preview, and the creator's reasoning. This project stores those fields in the content store and audit log.

## Anticipated Edge Cases

1. A poem with repeated short lines may look AI-like to the stylometric signal because it has low vocabulary diversity and repeated structure, even if the repetition is intentional.
2. A polished scholarship essay by a human may look AI-like because it uses formal transitions and balanced sentences.
3. A short text under about 40 words may not provide enough evidence for stable sentence variation or vocabulary diversity.
4. Edited AI output with personal details may score human-like because the surface style has been changed.

## Rate Limit Plan

The `/submit` endpoint will use `10 per minute` and `100 per day` per client IP. A normal writer might test a few drafts quickly, so 10 per minute allows normal use. A script trying to flood the system would hit the limit quickly. The daily limit is high enough for a busy creator but low enough for a class project abuse guard.

## AI Tool Plan

### M3: Submission endpoint and first signal

I will give the AI tool the architecture diagram and the semantic signal section. I will ask it for a Flask app skeleton with `POST /submit`, a content ID in the response, a placeholder confidence score, and a semantic signal function. I will verify by calling the signal directly with a few text samples and then sending a JSON request to the endpoint.

### M4: Second signal and confidence scoring

I will give the AI tool the detection signals, uncertainty representation, and architecture diagram. I will ask for the stylometric signal, the formulaic phrase signal, and the weighted scoring function. I will check that the thresholds match this plan exactly and test at least four examples: obvious AI, casual human, formal human, and lightly edited AI.

### M5: Production layer

I will give the AI tool the label variants, appeals workflow, rate limit plan, and architecture diagram. I will ask for a label function, `/appeal`, `/log`, and rate limiting on `/submit`. I will verify that all three labels are reachable, appeals update status to `under_review`, and rapid submissions trigger a `429` response.
