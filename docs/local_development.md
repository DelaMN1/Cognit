# Local Development

## Install

```bash
pip install -e ".[dev,ai,gemini,examples]"
```

## Useful Commands

```bash
pytest
ruff check .
python -m cognit.cli --help
python -m cognit.cli verify-services --help
python -m cognit.cli run-bot --help
```

## Manual Verification Checklist

1. Install the package:

```bash
pip install -e ".[dev,gemini]"
```

2. Verify services:

```bash
cognit verify-services --provider gemini
```

3. Trigger a manual alert:

```bash
python -c "import logging; from cognit import CognitHandler; logger=logging.getLogger('cognit.manual'); logger.handlers.clear(); logger.propagate=False; logger.setLevel(logging.ERROR); logger.addHandler(CognitHandler(app_name='manual-test', environment='dev')); \
try: raise RuntimeError('manual alert test')\
except RuntimeError: logger.exception('Manual alert test')"
```

4. Start the bot:

```bash
cognit run-bot
```

5. Ask a follow-up question in Telegram:

```text
/cognit <incident_id> What caused this?
```

After the alert arrives, you can also reply with plain text such as `What caused this?`. Use `/current` to check the active incident and `/clear` to reset it.

6. Run tests:

```bash
pytest
```

7. Run lint:

```bash
ruff check .
```

## Example Apps

- `python examples/simple_script/app.py`
- `python examples/flask_app/app.py`
- `python examples/fastapi_app/app.py`
