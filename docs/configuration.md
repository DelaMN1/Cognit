# Configuration

Cognit reads configuration from environment variables when `CognitConfig.from_env()` runs.

## Core Settings

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_APP_NAME` | App label shown in incidents and alerts | `cognit-app` |
| `COGNIT_ENVIRONMENT` | Environment label | `development` |
| `COGNIT_ENABLE_CAPTURE` | Enable or disable handler capture | `true` |
| `COGNIT_TAGS` | Comma-separated tags like `team:platform,service:api` | empty |

## AI Provider Settings

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_AI_PROVIDER` | `openai`, `gemini`, or `fallback` | `openai` |
| `COGNIT_OPENAI_API_KEY` | OpenAI API key | empty |
| `COGNIT_OPENAI_MODEL` | OpenAI analysis model | `gpt-4.1-mini` |
| `COGNIT_OPENAI_EMBEDDING_MODEL` | OpenAI embedding model | `text-embedding-3-small` |
| `COGNIT_GEMINI_API_KEY` | Gemini API key | empty |
| `COGNIT_GEMINI_MODEL` | Gemini analysis model | `gemini-2.5-flash` |
| `COGNIT_ENABLE_AI_ANALYSIS` | Enable provider or fallback analysis | `true` |

## Telegram Settings

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_TELEGRAM_BOT_TOKEN` | Telegram bot token | empty |
| `COGNIT_TELEGRAM_CHAT_ID` | Telegram target chat ID | empty |
| `COGNIT_ENABLE_TELEGRAM_ALERTS` | Enable Telegram alerts | `true` |

## Alert Noise Controls

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_ENABLE_DEDUPLICATION` | Enable duplicate suppression | `true` |
| `COGNIT_DEDUPE_WINDOW_SECONDS` | Duplicate window | `300` |
| `COGNIT_ENABLE_RATE_LIMITING` | Enable Telegram rate limiting | `true` |
| `COGNIT_TELEGRAM_ALERT_LIMIT` | Max sent alerts inside the rate window | `10` |
| `COGNIT_TELEGRAM_ALERT_WINDOW_SECONDS` | Rate limit window | `60` |

## Follow-Up Context Limits

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_MAX_FOLLOWUP_CONTEXT_CHARS` | Max compact provider prompt size for follow-up questions | `6000` |
| `COGNIT_MAX_CONVERSATION_HISTORY_MESSAGES` | Max recent conversation messages included in follow-up context | `4` |
| `COGNIT_MAX_SIMILAR_INCIDENTS_FOR_FOLLOWUP` | Max similar incidents included in follow-up context | `2` |
| `COGNIT_MAX_SIMILAR_INCIDENT_CHARS` | Max characters per similar-incident summary | `800` |

## Redaction

| Variable | Purpose | Default |
| --- | --- | --- |
| `COGNIT_REDACTION_PATTERNS` | Comma-separated custom regex patterns | empty |

## Recommended Local Gemini `.env`

```env
COGNIT_APP_NAME=my-app
COGNIT_ENVIRONMENT=development
COGNIT_AI_PROVIDER=gemini
COGNIT_GEMINI_API_KEY=your_gemini_api_key_here
COGNIT_GEMINI_MODEL=gemini-2.5-flash
COGNIT_TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
COGNIT_TELEGRAM_CHAT_ID=your_chat_id_here
COGNIT_MAX_FOLLOWUP_CONTEXT_CHARS=6000
COGNIT_MAX_CONVERSATION_HISTORY_MESSAGES=4
COGNIT_MAX_SIMILAR_INCIDENTS_FOR_FOLLOWUP=2
COGNIT_MAX_SIMILAR_INCIDENT_CHARS=800
```
