"""Send the daily walk to Telegram.

Usage:
    uv run send-walk               plan a walk and send it to TELEGRAM_CHAT_ID
    uv run send-walk --lang en     message language for this run (fr or en, overrides WALK_LANG)
    uv run send-walk --no-record   send without saving the walk to the history
    uv run send-walk --find-chat   read the bot's latest update and save TELEGRAM_CHAT_ID to .env

Secrets come from .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) and are never printed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from autumn_walks.config import DAILY_QUESTION
from autumn_walks.load_trees import ROOT
from autumn_walks.tools import GENUS_INFO, walk_lang

ENV_PATH = ROOT / ".env"
API = "https://api.telegram.org/bot{token}/{method}"


def load_env() -> dict[str, str]:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return env


def _call(token: str, method: str, params: dict | None = None) -> dict:
    data = urllib.parse.urlencode(params).encode() if params else None
    url = API.format(token=token, method=method)
    try:
        with urllib.request.urlopen(url, data=data, timeout=20) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        body = json.load(e)
    if not body.get("ok"):
        # The URL holds the token, so only report Telegram's own description.
        raise RuntimeError(f"Telegram {method} failed: {body.get('description', 'unknown error')}")
    return body["result"]


def find_chat_id() -> None:
    env = load_env()
    if "TELEGRAM_CHAT_ID" in env:
        print("TELEGRAM_CHAT_ID is already in .env; nothing to do.")
        return
    updates = _call(env["TELEGRAM_BOT_TOKEN"], "getUpdates")
    chats = [u["message"]["chat"] for u in updates if "message" in u]
    if not chats:
        sys.exit("No message found. Send any message to the bot in Telegram, then retry.")
    chat = chats[-1]
    text = ENV_PATH.read_text(encoding="utf-8")
    sep = "" if text.endswith("\n") else "\n"
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{sep}TELEGRAM_CHAT_ID={chat['id']}\n")
    print(f"Saved TELEGRAM_CHAT_ID to .env (a {chat['type']} chat).")


def send_message(text: str) -> None:
    env = load_env()
    _call(env["TELEGRAM_BOT_TOKEN"], "sendMessage", {"chat_id": env["TELEGRAM_CHAT_ID"], "text": text})


def main() -> None:
    parser = argparse.ArgumentParser(prog="send-walk", description="Plan an autumn walk and send it on Telegram.")
    parser.add_argument("--lang", choices=sorted(GENUS_INFO), help="message language (overrides WALK_LANG)")
    parser.add_argument("--no-record", action="store_true", help="do not save the walk to the history")
    parser.add_argument("--find-chat", action="store_true", help="save TELEGRAM_CHAT_ID to .env and exit")
    args = parser.parse_args()

    if args.find_chat:
        find_chat_id()
        return
    if args.lang:
        os.environ["WALK_LANG"] = args.lang

    # Imported here so --find-chat works without Ollama.
    from autumn_walks.agent import plan_walk
    from autumn_walks.history import record_walk

    stamp = datetime.now().isoformat(timespec="seconds")
    result = plan_walk(DAILY_QUESTION[walk_lang()])
    for n, reason in enumerate(result.retry_reasons, 1):
        print(f"{stamp} retry {n}: {reason}")
    if not result.ready:
        sys.exit(f"{stamp} not sent: the message failed its checks after {result.retries} retries.")
    send_message(result.message)
    if not args.no_record:
        record_walk(result.walk)
    stops = ", ".join(s["place"] for s in result.walk["stops"])
    note = " (not recorded)" if args.no_record else ""
    print(f"{stamp} sent{note}: {result.walk['total_distance']}, {stops}")


if __name__ == "__main__":
    main()
