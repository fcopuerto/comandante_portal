import os
import asyncio
from telethon import TelegramClient, events


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing env var: {name}")
    return val


def _parse_target(s: str | None):
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return s  # allow @username


async def main():
    api_id = int(_require_env("TELEGRAM_API_ID"))
    api_hash = _require_env("TELEGRAM_API_HASH")
    target = _parse_target(os.environ.get("TELEGRAM_CHAT_ID"))
    client = TelegramClient("telethon_session", api_id, api_hash)

    async with client:
        if target is None:
            target = input("Chat @username or ID: ").strip()
        entity = await client.get_entity(target)

        # Read last 50 messages (history)
        msgs = await client.get_messages(entity, limit=50)
        for m in reversed(msgs):
            text = (m.message or "").replace("\n", " ")
            print(f"[{m.date:%Y-%m-%d %H:%M:%S}] {m.sender_id}: {text}")

        # Listen to new messages
        print("Listening for new messages (Ctrl+C to exit)...")

        @client.on(events.NewMessage(chats=entity))
        async def handler(event):
            msg = event.message
            text = (msg.message or "").replace("\n", " ")
            print(f"[{msg.date:%Y-%m-%d %H:%M:%S}] {msg.sender_id}: {text}")

        await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
