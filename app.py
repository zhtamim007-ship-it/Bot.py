import hmac
import os
import threading

import requests
from flask import Flask, request

app = Flask(__name__)

# Values will be added in Render, not in this file.
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_TELEGRAM_ID"])
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]

GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_REPO = os.environ.get(
    "GITHUB_REPO", "zhtamim007-ship-it/Bot.py"
)
GH_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "main.yml")
GH_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
GH_BASE = f"https://api.github.com/repos/{GH_REPO}"

# Run one Gunicorn worker in Render.
lock = threading.Lock()
processed = set()
processed_order = []

MENU = {
    "inline_keyboard": [
        [{"text": "▶ Start Session", "callback_data": "start"}],
        [{"text": "📊 Check Status", "callback_data": "status"}],
        [{"text": "⏹ Stop Session", "callback_data": "stop"}],
        [{"text": "ℹ Help", "callback_data": "help"}],
    ]
}

ACTIVE_STATES = {
    "queued",
    "in_progress",
    "waiting",
    "pending",
    "requested",
}


def telegram(method, data):
    response = requests.post(
        f"{TG_BASE}/{method}", json=data, timeout=15
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram request failed")
    return result


def send(text, keyboard=None):
    return telegram(
        "sendMessage",
        {
            "chat_id": OWNER_ID,
            "text": text,
            "reply_markup": keyboard or MENU,
        },
    )


def github(method, path, **kwargs):
    response = requests.request(
        method,
        f"{GH_BASE}{path}",
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
        **kwargs,
    )
    response.raise_for_status()
    if response.status_code == 204:
        return None
    return response.json()


def workflow_runs(page=1, size=100):
    return github(
        "GET",
        f"/actions/workflows/{GH_WORKFLOW}/runs",
        params={
            "branch": GH_BRANCH,
            "event": "workflow_dispatch",
            "per_page": size,
            "page": page,
        },
    )["workflow_runs"]


def active_runs():
    found = []
    page = 1
    while True:
        runs = workflow_runs(page)
        found.extend(
            run for run in runs
            if run["status"] in ACTIVE_STATES
        )
        if len(runs) < 100:
            return found
        page += 1


def handle(action):
    if action == "start":
        runs = active_runs()
        if runs:
            send(
                "A workflow is already active.\n"
                "Use Check Status or Stop Session."
            )
            return

        github(
            "POST",
            f"/actions/workflows/{GH_WORKFLOW}/dispatches",
            json={"ref": GH_BRANCH},
        )
        send(
            "Start request accepted by GitHub.\n"
            "This does not mean Windows is ready yet.\n"
            "Wait a little, then press Check Status."
        )

    elif action == "status":
        runs = workflow_runs(size=1)
        if not runs:
            send("No manually triggered workflow run found.")
            return

        run = runs[0]
        send(
            f"Latest workflow run: {run['id']}\n"
            f"Status: {run['status']}\n"
            f"Result: {run.get('conclusion') or 'Not finished'}\n\n"
            f"{run['html_url']}\n\n"
            "Workflow status is not an RDP connection test."
        )

    elif action == "stop":
        runs = active_runs()
        if not runs:
            send("No active workflow found.")
            return

        # Show one exact run for confirmation.
        run = runs[0]
        send(
            f"Cancel workflow run {run['id']}?\n"
            "Its hosted runner session will end.\n"
            "Unsaved data may be lost.\n\n"
            f"{run['html_url']}",
            {
                "inline_keyboard": [
                    [{
                        "text": "Yes, stop this run",
                        "callback_data": f"cancel:{run['id']}",
                    }],
                    [{
                        "text": "No, go back",
                        "callback_data": "menu",
                    }],
                ]
            },
        )

    elif action.startswith("cancel:"):
        run_id = action.split(":", 1)[1]
        if not run_id.isdigit():
            send("Invalid request.")
            return

        # Verify that the selected run still belongs to
        # this workflow/branch and is still active.
        allowed = {
            str(run["id"]): run for run in active_runs()
        }
        if run_id not in allowed:
            send("That run is no longer active or is not in scope.")
            return

        github("POST", f"/actions/runs/{run_id}/cancel")
        send(
            "Cancellation requested.\n"
            "Use Check Status to verify it has stopped.\n"
            "This does not remove Tailscale device records."
        )

    elif action == "help":
        send(
            "Start: request a workflow run.\n"
            "Status: show the latest workflow run.\n"
            "Stop: confirm cancellation of an active run.\n\n"
            "Keep your phone signed in to your own Tailscale "
            "account. Windows connection details will be "
            "added in the workflow integration step."
        )

    else:
        send("Your private workflow controller is ready.")


@app.get("/")
def health():
    return {"ok": True}


@app.post("/telegram")
def webhook():
    provided = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )
    if not hmac.compare_digest(provided, WEBHOOK_SECRET):
        return "Forbidden", 403

    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return "Bad request", 400

    callback = update.get("callback_query")
    message = (
        callback.get("message", {})
        if callback
        else update.get("message", {})
    )
    sender = (
        callback.get("from", {})
        if callback
        else message.get("from", {})
    )
    chat = message.get("chat", {})

    if (
        sender.get("id") != OWNER_ID
        or chat.get("id") != OWNER_ID
        or chat.get("type") != "private"
    ):
        return "OK", 200

    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return "Bad request", 400

    with lock:
        if update_id in processed:
            return "OK", 200

        processed.add(update_id)
        processed_order.append(update_id)
        if len(processed_order) > 1000:
            processed.discard(processed_order.pop(0))

        if callback:
            try:
                telegram(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"]},
                )
            except requests.RequestException:
                pass
            action = callback.get("data", "menu")
        else:
            commands = {
                "/start": "menu",
                "/status": "status",
                "/stop": "stop",
                "/help": "help",
            }
            action = commands.get(
                message.get("text", "").strip(), "menu"
            )

        try:
            handle(action)
        except Exception:
            # Do not print exception details containing credentials.
            app.logger.warning("Bot operation failed")
            try:
                send(
                    "Operation could not be confirmed.\n"
                    "Check GitHub before retrying Start.\n"
                    "Check Render environment settings as well."
                )
            except Exception:
                app.logger.warning("Error notification failed")

    return "OK", 200
    
