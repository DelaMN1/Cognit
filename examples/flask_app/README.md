# Flask Example

This example attaches `CognitHandler` to a Flask app and exposes `/error`.

## Run It

1. Install Cognit with the example dependencies:

```bash
pip install -e ".[dev,gemini,examples]"
```

2. Copy `.env.example` to `.env` and fill in your real values.

3. Verify services:

```bash
cognit verify-services --provider gemini
```

4. Start the app:

```bash
python examples/flask_app/app.py
```

5. Trigger one safe test exception:

```bash
curl http://127.0.0.1:5000/error
```

The route catches the sample exception, logs it through Cognit, and returns a `500` response.
