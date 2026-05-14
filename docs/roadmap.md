# Roadmap

## MVP Definition of Done

- [x] Cognit captures Python exceptions as structured incidents.
- [x] Cognit redacts secrets before storage, embeddings, AI, and Telegram.
- [x] Cognit stores incidents in SQLite.
- [x] Cognit suppresses duplicate alerts and rate-limits alert storms.
- [x] Cognit retrieves similar incidents.
- [x] Cognit sends Telegram alerts with incident IDs.
- [x] Cognit supports `/cognit <incident_id> <question>` follow-up replies.
- [x] Cognit provides manual verification commands for services and Telegram delivery.
- [x] Cognit includes example apps, docs, tests, and CI coverage.

## Future Work

- Webhook-based Telegram delivery
- Additional providers and richer provider-specific controls
- Better deployment recipes for production services
- Broader example coverage beyond the current script, Flask, and FastAPI examples
- Optional remote or team-shared storage backends
