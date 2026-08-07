"""
backup.py – Automated SQLite backups.
Runs a daily snapshot in a background thread, keeps the last N copies
on the same persistent volume as the live database.
"""
import os, shutil, threading, time
from datetime import datetime

KEEP_BACKUPS = 14  # keep last 14 daily snapshots


def backup_dir(db_path):
    d = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def make_backup(db_path):
    if not os.path.exists(db_path):
        return None
    d = backup_dir(db_path)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    dest  = os.path.join(d, f"eligald_{stamp}.db")
    try:
        shutil.copy2(db_path, dest)
        _prune(d)
        return dest
    except Exception as e:
        print(f"[BACKUP] Failed: {e}")
        return None


def _prune(d):
    files = sorted(
        [f for f in os.listdir(d) if f.startswith("eligald_") and f.endswith(".db")],
        reverse=True
    )
    for old in files[KEEP_BACKUPS:]:
        try: os.remove(os.path.join(d, old))
        except Exception: pass


def list_backups(db_path):
    d = backup_dir(db_path)
    files = sorted(
        [f for f in os.listdir(d) if f.startswith("eligald_") and f.endswith(".db")],
        reverse=True
    )
    return [{
        "name": f,
        "path": os.path.join(d, f),
        "size_kb": round(os.path.getsize(os.path.join(d, f)) / 1024, 1),
        "created": datetime.fromtimestamp(os.path.getmtime(os.path.join(d, f))).strftime("%Y-%m-%d %H:%M")
    } for f in files]


def start_daily_backup_thread(db_path, interval_hours=24):
    """Runs make_backup() once on startup, then every interval_hours."""
    def loop():
        # Small delay so the app finishes booting first
        time.sleep(30)
        while True:
            make_backup(db_path)
            time.sleep(interval_hours * 3600)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
