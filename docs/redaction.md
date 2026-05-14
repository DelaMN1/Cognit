# Redaction

Cognit redacts supported secrets before it stores incidents, builds embeddings, calls AI providers, or sends Telegram messages.

## Built-In Coverage

Cognit redacts:

- API keys
- OpenAI-style keys
- GitHub tokens
- bearer tokens
- JWTs
- password fields
- database URLs
- Redis URLs with passwords
- private key blocks
- emails
- phone numbers
- credit-card-like numbers
- custom regex matches

## Practical Rules

- Put real credentials in `.env`, not in source files.
- Do not commit `.env`.
- Expect Telegram, SQLite, and AI providers to receive only redacted content.
- Add custom regex patterns through `COGNIT_REDACTION_PATTERNS` when your app uses project-specific secret formats.

## Limits

Redaction helps, but it does not replace careful application logging. Avoid logging secrets at the source whenever possible.
