import sqlite3, time, json
from pathlib import Path

c = sqlite3.connect(r"data/checkapp.db")
c.row_factory = sqlite3.Row
print("=== chat ===")
for r in c.execute("SELECT id,steam_id,steam_name,substr(text,1,50) t,target_steam_id,from_site,created_at FROM chat ORDER BY id DESC LIMIT 10"):
    print(dict(r))
print("=== bags ===")
for r in c.execute("SELECT id,net_id,steam_id,name,grid,project_id FROM bags ORDER BY id DESC LIMIT 20"):
    print(dict(r))
print("=== signage ===")
for r in c.execute("SELECT id,net_id,steam_id,destroyed_at,project_id,created_at, length(image) img_len FROM signage ORDER BY id DESC LIMIT 20"):
    print(dict(r))
print("=== alerts ===")
for r in c.execute("SELECT id,type,steam_id,substr(payload,1,120) p,created_at FROM alerts ORDER BY id DESC LIMIT 15"):
    print(dict(r))
print("=== mutes ===")
try:
    for r in c.execute("SELECT * FROM player_mutes ORDER BY id DESC LIMIT 8"):
        print(dict(r))
except Exception as e:
    print("mutes err", e)
    print([x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
print("=== queue ===")
try:
    for r in c.execute("SELECT id,name,substr(data,1,100) d,done,created_at FROM queue ORDER BY rowid DESC LIMIT 12"):
        print(dict(r))
except Exception as e:
    print("queue", e)
print("now", int(time.time()))
