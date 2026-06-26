# ...new file...
from telethon import TelegramClient
import os

API_ID = int(os.environ.get("TELEGRAM_API_ID") or input("API_ID: "))
API_HASH = os.environ.get("TELEGRAM_API_HASH") or input("API_HASH: ")

with TelegramClient('cobaltax_user_session', API_ID, API_HASH) as client:
    for dlg in client.iter_dialogs():
        ent = dlg.entity
        is_channel = getattr(ent, 'broadcast', False) or getattr(ent, 'megagroup', False)
        nid = getattr(ent, 'id', None)
        # Bot API style id for channels/supergroups needs -100 prefix
        bot_api_chat_id = f"-100{nid}" if is_channel and nid is not None else nid
        title = dlg.title or getattr(ent, 'username', None) or str(nid)
        print(f"{title!r}  | entity_id={nid}  | bot_api_chat_id={bot_api_chat_id}")
# ...new file...