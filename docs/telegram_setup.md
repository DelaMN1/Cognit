# Telegram Setup

## 1. Create the Bot

1. Open Telegram and talk to `@BotFather`.
2. Create a new bot.
3. Copy the bot token into your local `.env` file.

## 2. Get the Chat ID

1. Open a chat with your bot.
2. Send the bot a message first.
3. Put the target chat ID into `.env`.

```env
COGNIT_TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
COGNIT_TELEGRAM_CHAT_ID=your_chat_id_here
```

## 3. Verify Delivery

Run:

```bash
cognit test-telegram
```

If this fails, fix Telegram before testing the rest of Cognit.

## 4. Verify the Provider Path

Run:

```bash
cognit verify-services --provider gemini
```

This checks both the selected AI provider and Telegram delivery.

## 5. Start the Follow-Up Bot

Run:

```bash
cognit run-bot
```

After Cognit sends a real alert, you can:

- use `/cognit <incident_id> <question>`
- reply with plain text like `What caused this?`
- use `/current` to inspect the active incident for the chat
- use `/clear` to reset the active incident
