from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
import asyncio
import os
import sys
from telegram import Update
from telegram.ext import Application, MessageHandler, ChannelPostHandler, ContextTypes, filters

# Ensure project root is on sys.path to import config.py
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _parse_chat_id(cid: str | None):
    if not cid:
        return None
    try:
        return int(cid)
    except Exception:
        return cid  # accept @username


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    user = update.effective_user
    text = msg.text or msg.caption or ""
    print(f"[{msg.date:%Y-%m-%d %H:%M:%S}] {user.id if user else '?'}: {text}")


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN missing in config.py or environment")

    chat_filter = filters.ALL
    target = _parse_chat_id(TELEGRAM_CHAT_ID)
    if target is not None:
        chat_filter = filters.Chat(target)

    async def _post_init(app: Application):
        # Remove webhook if set and drop pending updates to avoid conflicts
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_post_init).build()
    # For group/supergroup direct messages
    app.add_handler(MessageHandler(
        chat_filter & ~filters.StatusUpdate.ALL, on_message))
    # For channel posts (if TELEGRAM_CHAT_ID is a channel)
    app.add_handler(ChannelPostHandler(chat_filter, on_message))

    # Receive both group messages and channel posts
    app.run_polling(
        allowed_updates=["message", "edited_message",
                         "channel_post", "edited_channel_post"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
