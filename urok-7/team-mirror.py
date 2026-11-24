import argparse
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("task")
p.add_argument("--target", required=True, help="telegram:ID или telegram:ID:тема")
p.add_argument("--state", required=True, type=Path)
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()
if not a.target.startswith("telegram:") or not a.target.split(":")[1].lstrip("-").isdigit():
    p.error("Укажи выбранный чат Telegram по номеру")
raw = subprocess.check_output(["hermes", "kanban", "show", a.task, "--json"], text=True)
comments = json.loads(raw)["comments"]
with sqlite3.connect(a.state, timeout=20) as db:
    db.execute("CREATE TABLE IF NOT EXISTS delivery (event TEXT PRIMARY KEY, status TEXT NOT NULL)")
    for n, c in enumerate(comments):
        if c["author"] not in ("collector", "controller", "repairer", "analyst"):
            continue
        if not c["body"].startswith("В чат: "):
            continue
        message = f'{c["author"]} · {a.task}\n{c["body"][7:]}'
        if a.dry_run:
            print(message)
            continue
        event = hashlib.sha256(json.dumps([a.target, a.task, n, c], sort_keys=True).encode()).hexdigest()
        inserted = db.execute("INSERT OR IGNORE INTO delivery VALUES (?, 'sending')", (event,)).rowcount
        db.commit()
        if not inserted:
            status = db.execute("SELECT status FROM delivery WHERE event=?", (event,)).fetchone()[0]
            if status != "sent":
                raise SystemExit("Проверь доставку в чате перед повтором: " + event)
            continue
        response = subprocess.run(["hermes", "send", "--to", a.target, "--file", "-", "--json"],
                                  input=message, text=True, capture_output=True, check=True)
        receipt = json.loads(response.stdout)
        if not receipt.get("success") or receipt.get("skipped") or not receipt.get("message_id"):
            raise SystemExit("Telegram не подтвердил отправку. Сверь историю чата: " + event)
        db.execute("UPDATE delivery SET status='sent' WHERE event=?", (event,))
        db.commit()
