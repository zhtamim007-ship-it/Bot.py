import os
import secrets
import sys

import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
base = f"https://api.telegram.org/bot{token}/"


def call(method, payload=None):
    response = requests.post(
        base + method,
        json=payload or {},
        timeout=20,
    )
    result = response.json()
    if not result.get("ok"):
        raise SystemExit(
            "Telegram request failed: "
            + result.get("description", "unknown error")
        )
    return result.get("result")


mode = sys.argv[1]

if mode == "whoami":
    info = call("getWebhookInfo")
    if info.get("url"):
        raise SystemExit(
            "Webhook already exists. This lookup is only for initial setup."
        )

    updates = call("getUpdates")
    for update in updates:
        msg = update.get("message", {})
        chat = msg.get("chat", {})
        user = msg.get("from", {})
        if chat.get("type") == "private":
            print("Name:", user.get("first_name"))
            print("Numeric user ID:", user.get("id"))

elif mode == "secret":
    print(secrets.token_urlsafe(32))

elif mode == "webhook":
    public_url = os.environ["PUBLIC_URL"].rstrip("/")
    call(
        "setWebhook",
        {
            "url": public_url + "/telegram",
            "secret_token": os.environ["TELEGRAM_WEBHOOK_SECRET"],
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
        },
    )
    print("Webhook configured.")

else:
    raise SystemExit("Use: whoami | secret | webhook")
