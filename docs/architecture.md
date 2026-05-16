# Architecture

Cognit uses a small local architecture:

1. `CognitHandler` converts Python `LogRecord` objects into `LogEvent` incidents.
2. The redactor removes sensitive values before any storage or provider call.
3. SQLite stores incidents, analyses, embeddings, Telegram results, and follow-up conversation messages.
4. Deduplication and rate limiting decide whether Cognit should send a Telegram alert.
5. The analyzer uses Gemini, OpenAI, or the fallback analyzer.
6. The embedder stores vectors for similar-incident lookup.
7. The Telegram client sends alerts and the follow-up bot polls for `/cognit` questions.

## Main Runtime Paths

### Alert Path

1. App code calls `logger.exception(...)`.
2. `CognitHandler` builds and redacts the incident.
3. SQLite persists the incident when storage is available.
4. Dedupe and rate limiting decide whether Telegram should send.
5. Cognit loads similar incidents and generates analysis.
6. Cognit stores analysis and embeddings.
7. Cognit sends a Telegram alert if suppression does not apply.
8. If Telegram sends at least one alert message successfully, Cognit stores active chat context for follow-up routing.

### Follow-Up Path

1. `cognit run-bot` starts Telegram polling.
2. The bot accepts `/cognit <incident_id> <question>` or plain-text replies when active chat context exists.
3. `/current` shows the active incident for the chat and `/clear` removes it.
4. The bot loads compact incident context, recent conversation, and limited similar incidents.
5. The bot redacts the question and all loaded context before provider calls.
6. The selected provider or fallback path generates a plain-text answer.
7. Cognit stores the user question and the bot reply in SQLite.

## Storage

SQLite lives at `.cognit/cognit.db` by default. Cognit uses:

- WAL mode
- `busy_timeout=5000`
- short-lived connections
- a write lock around writes

## Boundaries

- Cognit does not replace application logs.
- Cognit does not send raw secrets to Gemini, OpenAI, or Telegram.
- Cognit does not depend on a remote backend for MVP use.
