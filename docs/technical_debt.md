# Technical Debt

Current debt is deliberate and visible:

- The Telegram bot uses polling instead of webhooks.
- SQLite is local-only and fits MVP usage better than multi-user deployments.
- The current AI interfaces focus on alert analysis and follow-up answers, not arbitrary tool use.
- The examples are intentionally small and do not cover deployment, auth, or production server setup.
- The docs assume a local `.env` workflow and do not describe secret managers yet.

These items are future work, not hidden behavior.
