import hmac
import logging
import os
import re
import threading

import requests
from flask import Flask, abort, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OWNER_ID = int(os.environ["TELEGRAM_OWNER_ID"])
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]

GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_REPO = os.environ["GITHUB_REPO"]
GH_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "main.yml")
GH_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

GH_BASE = f"https://api.github.com/repos/{GH_REPO}"

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Serializes commands within this single Render process.
command_lock = threading.Lock()

KEYBOARD = {
    "keyboard": [
        ["▶ Start", "📊 Status"],
        ["⏹ Stop", "❓ Help"],
    ],
    "resize_keyboard": True,
}


def github(method, path, **kwargs):
    response = requests.request(
        method,
        GH_BASE + path,
        headers=HEADERS,
        timeout=10,
        **kwargs,
    )

    if not response.ok:
        # Do not expose API response bodies or tokens.
        raise RuntimeError(
            f"GitHub API returned HTTP {response.status_code}"
        )

    if response.status_code == 204:
        return None
    return response.json()


def workflow_runs():
    data = github(
        "GET",
        f"/actions/workflows/{GH_WORKFLOW}/runs",
        params={
            "branch": GH_BRANCH,
            "event": "workflow_dispatch",
            "per_page": 100,
        },
    )

    # Only recognize runs bearing our bot-specific run name.
    return [
        run
        for run in data.get("workflow_runs", [])
        if re.fullmatch(
            r"telegram-session-\d+",
            run.get("display_title", ""),
        )
    ]


def run_summary(run):
    state = run.get("conclusion") or run.get("status")
    return (
        f"Run: {run['id']}\n"
        f"State: {state}\n"
        f"{run['html_url']}"
    )


def handle_command(text, update_id):
    command = text.split()[0].split("@")[0] if text else ""

    if text == "❓ Help" or command in ("/start", "/help"):
        return (
            "এই বট তোমার নির্দিষ্ট GitHub workflow নিয়ন্ত্রণ করে।\n\n"
            "▶ Start — workflow শুরু\n"
            "📊 Status — সর্বশেষ bot session\n"
            "⏹ Stop — বন্ধ করার confirmation\n\n"
            "Windows প্রস্তুত হলে workflow আলাদা message পাঠাবে।"
        )

    if text == "▶ Start" or command == "/run":
        runs = workflow_runs()
        title = f"telegram-session-{update_id}"

        # Best-effort protection against Telegram delivery retries.
        previous = next(
            (run for run in runs
             if run.get("display_title") == title),
            None,
        )
        if previous:
            return "এই অনুরোধ আগেই গ্রহণ করা হয়েছে।\n" + run_summary(previous)

        active = [
            run for run in runs
            if run["status"] != "completed"
        ]
        if active:
            return "আগের session এখনও শেষ হয়নি।\n" + run_summary(active[0])

        github(
            "POST",
            f"/actions/workflows/{GH_WORKFLOW}/dispatches",
            json={
                "ref": GH_BRANCH,
                "inputs": {
                    "request_id": str(update_id),
                },
            },
        )
        return (
            "GitHub workflow request গ্রহণ করেছে।\n"
            "এখনই Windows ready হয়েছে—এমন নয়।\n"
            "কিছুক্ষণ পরে 📊 Status চাপো।"
        )

    if text == "📊 Status" or command == "/status":
        runs = workflow_runs()
        if not runs:
            return "এখনও কোনো bot session পাওয়া যায়নি।"
        return run_summary(runs[0])

    if text == "⏹ Stop" or command == "/stop":
        runs = workflow_runs()
        active = [
            run for run in runs
            if run["status"] != "completed"
        ]
        if not active:
            return "কোনো active bot session পাওয়া যায়নি।"

        run = active[0]
        return (
            "বন্ধ করলে unsaved কাজ হারাতে পারে।\n"
            "নিশ্চিত হলে এই command পাঠাও:\n\n"
            f"/confirm_stop {run['id']}\n\n"
            + run_summary(run)
        )

    if command == "/confirm_stop":
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return "সঠিক format: /confirm_stop RUN_ID"

        requested_id = int(parts[1])
        runs = workflow_runs()
        run = next(
            (item for item in runs if item["id"] == requested_id),
            None,
        )

        if not run:
            return "এই ID বর্তমান bot workflow-এর তালিকায় নেই।"

        if run["status"] == "completed":
            return "Session ইতিমধ্যে শেষ হয়েছে।"

        github(
            "POST",
            f"/actions/runs/{requested_id}/cancel",
        )
        return (
            "Cancel request পাঠানো হয়েছে।\n"
            "সম্পূর্ণ বন্ধ হয়েছে কি না 📊 Status দিয়ে যাচাই করো।"
        )

    return "নিচের বাটন ব্যবহার করো অথবা /help পাঠাও।"


@app.get("/")
def health():
    return {"ok": True}


@app.post("/telegram")
def telegram_webhook():
    supplied = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )
    if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
        abort(403)

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    sender = message.get("from") or {}
    chat = message.get("chat") or {}

    # Require a private message from the configured owner.
    if (
        sender.get("id") != OWNER_ID
        or chat.get("id") != OWNER_ID
        or chat.get("type") != "private"
    ):
        return jsonify(ok=True)

    text = message.get("text", "").strip()
    update_id = update.get("update_id")
    if not isinstance(update_id, int) or not text:
        return jsonify(ok=True)

    try:
        with command_lock:
            reply = handle_command(text, update_id)
    except Exception:
        # Avoid logging potentially sensitive request information.
        app.logger.error("Command processing failed")
        reply = (
            "অনুরোধের ফল নিশ্চিত করা যায়নি। "
            "আবার Start চাপার আগে Status দেখো। "
            "GitHub permission, configuration ও availability যাচাই করো।"
        )

    # Telegram can execute a method returned in the webhook response.
    return jsonify(
        method="sendMessage",
        chat_id=OWNER_ID,
        text=reply,
        reply_markup=KEYBOARD,
    )
