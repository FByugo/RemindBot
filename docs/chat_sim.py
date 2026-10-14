"""Walk the engine through a short chat, then a restart, to show what the adapters sit on."""
import time
from datetime import timedelta
from remindbot.engine import Engine, utcnow

db = "/tmp/remindbot-demo.db"
import os; os.path.exists(db) and os.remove(db)
e = Engine(db)
def say(text):
    print(f"  you › {text}"); time.sleep(0.6)
    print(f"  bot › {e.handle('chat1', 'you', text, utcnow())}\n"); time.sleep(0.9)
say("/tz America/New_York")
say("/remind in 3s stretch")
say("/remind 2 hours drink water")
say("/remind at 25:00 nonsense")
say("/list")
print("  ... bot restarts ..."); del e; time.sleep(1); e = Engine(db)
time.sleep(2.5)
for rid, chat, text in e.due(utcnow()):
    print(f"  bot › {text}"); e.mark_sent(rid, utcnow())
print(f"\n  pending after delivery: {e.handle('chat1','you','/list',utcnow())!r}")
