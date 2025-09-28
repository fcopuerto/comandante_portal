import os
import asyncio
from telethon import TelegramClient

api_id = int(os.environ['TELEGRAM_API_ID'])
api_hash = os.environ['TELEGRAM_API_HASH']
cid_raw = os.environ.get('TELEGRAM_CHAT_ID')

try:
    cid = int(cid_raw)
except Exception:
    cid = cid_raw


async def main():
    client = TelegramClient("cobaltax_user_session", api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print("Logged in as bot?", getattr(me, 'bot', False))
    try:
        entity = await client.get_entity(cid)
    except Exception:
        entity = None
        async for d in client.iter_dialogs():
            ent = d.entity
            base_id = getattr(ent, 'id', None)
            full_id = f"-100{base_id}" if ent.__class__.__name__ == 'Channel' else str(
                base_id)
            if str(full_id) == str(cid_raw):
                entity = ent
                break
    if not entity:
        print("Not found in dialogs. You are not a member.")
        return
    print("Resolved entity:", getattr(
        entity, 'title', getattr(entity, 'first_name', '?')))
    print("Recent messages:")
    async for msg in client.iter_messages(entity, limit=10):
        print("-", msg.date, (msg.message or "").replace("\n", " ")[:80])
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
