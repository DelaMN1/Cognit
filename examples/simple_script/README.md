# Simple Script Example

This example shows the smallest useful Cognit setup.

## Run It

1. Install Cognit and the Gemini provider:

```bash
pip install -e ".[dev,gemini]"
```

2. Copy `.env.example` to `.env` and fill in your real keys and Telegram values.

3. Verify external services:

```bash
cognit verify-services --provider gemini
```

4. Trigger one safe test exception:

```bash
python examples/simple_script/app.py
```

The script logs one handled `RuntimeError`. Cognit stores the incident locally and sends the alert if Telegram alerts are enabled.
