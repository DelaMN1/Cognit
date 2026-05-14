# Cognit

Cognit captures Python exceptions, stores them as structured incidents, analyzes them with Gemini, OpenAI, or a local fallback, and sends concise Telegram alerts with follow-up support.

## What Cognit Is

Cognit is a Python logging handler and local incident workflow. It turns `logger.exception(...)` calls into:

- redacted incident records in SQLite
- AI or fallback summaries
- Telegram alerts with incident IDs
- `/cognit <incident_id> <question>` follow-up replies in Telegram

## Why Cognit Exists

Teams often need a small incident tool before they need a full observability platform. Cognit focuses on a narrow loop:

1. Capture one structured incident from a real exception.
2. Redact secrets before storage or provider calls.
3. Send one useful alert instead of a flood of duplicates.
4. Let a developer ask a follow-up question from Telegram.

## Quickstart

1. Install Cognit with Gemini support:

```bash
pip install -e ".[dev,gemini]"
```

2. Copy `.env.example` to `.env` and fill in your real values.

3. Verify services:

```bash
cognit verify-services --provider gemini
```

4. Trigger one safe test incident:

```bash
python examples/simple_script/app.py
```

5. Start the follow-up bot in another terminal when you want Telegram follow-up replies:

```bash
cognit run-bot
```

The simple script example is the fastest path to a working alert.

## Installation

Core install:

```bash
pip install -e .
```

Gemini provider:

```bash
pip install -e ".[gemini]"
```

OpenAI provider:

```bash
pip install -e ".[ai]"
```

Example app dependencies:

```bash
pip install -e ".[examples]"
```

Full local development install:

```bash
pip install -e ".[dev,ai,gemini,examples]"
```

## .env Setup

Cognit loads configuration when `CognitConfig` is created. It does not load `.env` at module import time.

Example `.env`:

```env
COGNIT_APP_NAME=my-app
COGNIT_ENVIRONMENT=development
COGNIT_AI_PROVIDER=gemini
COGNIT_GEMINI_API_KEY=your_gemini_api_key_here
COGNIT_GEMINI_MODEL=gemini-2.5-flash
COGNIT_TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
COGNIT_TELEGRAM_CHAT_ID=your_chat_id_here
COGNIT_ENABLE_AI_ANALYSIS=true
COGNIT_ENABLE_TELEGRAM_ALERTS=true
COGNIT_ENABLE_DEDUPLICATION=true
COGNIT_DEDUPE_WINDOW_SECONDS=300
COGNIT_ENABLE_RATE_LIMITING=true
COGNIT_TELEGRAM_ALERT_LIMIT=10
COGNIT_TELEGRAM_ALERT_WINDOW_SECONDS=60
```

See [docs/configuration.md](/C:/Users/NANA/DESKTOP/Cognit/docs/configuration.md:1) for the full variable list.

## Gemini Setup

Gemini is the active provider for the current MVP manual path.

```env
COGNIT_AI_PROVIDER=gemini
COGNIT_GEMINI_API_KEY=your_gemini_api_key_here
COGNIT_GEMINI_MODEL=gemini-2.5-flash
```

Verify it:

```bash
cognit verify-services --provider gemini
```

Gemini Developer API has a free tier. Higher limits or production usage may require billing.

## OpenAI Setup

OpenAI remains supported for analysis and embeddings.

```env
COGNIT_AI_PROVIDER=openai
COGNIT_OPENAI_API_KEY=your_openai_api_key_here
COGNIT_OPENAI_MODEL=gpt-4.1-mini
COGNIT_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Verify it:

```bash
cognit verify-services --provider openai
```

## Fallback Mode

Fallback mode disables external AI calls and uses Cognit's deterministic local analysis path.

```env
COGNIT_AI_PROVIDER=fallback
```

Use fallback mode when you want local-only debugging output or when provider setup is not ready yet.

## Telegram Setup

Set the bot token and chat ID in `.env`:

```env
COGNIT_TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
COGNIT_TELEGRAM_CHAT_ID=your_chat_id_here
```

Then verify delivery:

```bash
cognit test-telegram
```

For a step-by-step Telegram setup guide, see [docs/telegram_setup.md](/C:/Users/NANA/DESKTOP/Cognit/docs/telegram_setup.md:1).

## Required Service Verification

Run these commands before manual testing:

```bash
cognit verify-services --provider gemini
cognit test-telegram
```

`cognit verify-services` checks the selected AI provider and Telegram delivery. `cognit test-telegram` sends a direct Telegram setup message and isolates Telegram-specific failures.

## Basic Python Example

```python
import logging

from cognit import CognitHandler

logger = logging.getLogger("demo")
logger.handlers.clear()
logger.propagate = False
logger.setLevel(logging.ERROR)
logger.addHandler(CognitHandler(app_name="demo", environment="development"))

try:
    raise RuntimeError("basic example test exception")
except RuntimeError:
    logger.exception("Basic example test exception")
```

The same flow appears in [examples/simple_script/app.py](/C:/Users/NANA/DESKTOP/Cognit/examples/simple_script/app.py:1).

## Flask Example

Run:

```bash
python examples/flask_app/app.py
```

Trigger the safe exception:

```bash
curl http://127.0.0.1:5000/error
```

See [examples/flask_app/README.md](/C:/Users/NANA/DESKTOP/Cognit/examples/flask_app/README.md:1).

## FastAPI Example

Run:

```bash
python examples/fastapi_app/app.py
```

Trigger the safe exception:

```bash
curl http://127.0.0.1:8000/error
```

See [examples/fastapi_app/README.md](/C:/Users/NANA/DESKTOP/Cognit/examples/fastapi_app/README.md:1).

## How Alerts Work

When Cognit receives an eligible log record, it:

1. converts it into a structured incident
2. redacts sensitive values
3. stores the incident in SQLite
4. suppresses duplicates when the fingerprint matches within the dedupe window
5. suppresses Telegram sends when the rate limit has already been reached
6. retrieves similar incidents
7. generates AI or fallback analysis
8. sends a Telegram alert unless suppression applies

Telegram alerts include the incident ID and a ready-to-use follow-up command.

## How `/cognit` Follow-Up Works

Start the bot:

```bash
cognit run-bot
```

Then ask:

```text
/cognit <incident_id> What caused this?
```

The bot loads the incident, recent follow-up history, and similar incidents, redacts the context, asks the selected provider, saves the question and answer, and replies in Telegram.

## Redaction and Security

Cognit redacts secrets before storage, AI analysis, embeddings, and Telegram delivery. It masks API keys, passwords, database URLs, emails, tokens, and other supported patterns.

Rules that matter in practice:

- Keep real secrets only in your local `.env`.
- Do not commit `.env`.
- Treat AI providers as redacted-context services, not raw log sinks.
- Use `cognit verify-services` and `cognit test-telegram` before real incident tests.

See [docs/redaction.md](/C:/Users/NANA/DESKTOP/Cognit/docs/redaction.md:1) for more detail.

## SQLite Storage

Cognit stores incidents in `.cognit/cognit.db` by default. The SQLite layer uses WAL mode, a short connection-per-operation pattern, and a write lock around writes.

Stored tables include:

- `incidents`
- `logs`
- `embeddings`
- `telegram_messages`
- `conversations`
- `alert_events`

## Deduplication and Rate Limiting

Deduplication suppresses repeat alerts for the same fingerprint inside the dedupe window. Rate limiting suppresses excess Telegram sends based on recently sent alert records stored in SQLite.

These controls reduce alert noise without discarding the incident history.

## Similar Incident Retrieval

Cognit stores embeddings and retrieves similar incidents when possible. It uses OpenAI embeddings if OpenAI is configured and falls back to deterministic local hash embeddings otherwise.

The retriever:

- excludes the current incident
- prefers the same app and environment
- skips corrupt embeddings
- skips wrong-dimension embeddings

## Known MVP Limitations

- Cognit only targets Python logging today.
- The bot uses Telegram polling, not webhooks.
- The project stores data in local SQLite, not a remote multi-user backend.
- Follow-up responses use redacted context, so deep root-cause analysis still depends on the original application logs and codebase.
- The examples are intentionally small and are not production deployment templates.

## Development Setup

Use the full dev install:

```bash
pip install -e ".[dev,ai,gemini,examples]"
```

Main local commands:

```bash
pytest
ruff check .
python -m cognit.cli --help
python -m cognit.cli verify-services --help
python -m cognit.cli run-bot --help
```

See [docs/local_development.md](/C:/Users/NANA/DESKTOP/Cognit/docs/local_development.md:1) for the complete workflow and manual verification checklist.

## Roadmap

The MVP is complete when the current handler, alert, similar-incident, and follow-up loop all work together with local verification. Remaining work belongs in future phases such as richer providers, webhook-based bot delivery, and broader framework coverage.

See [docs/roadmap.md](/C:/Users/NANA/DESKTOP/Cognit/docs/roadmap.md:1).

## License

Cognit is released under the MIT License.
