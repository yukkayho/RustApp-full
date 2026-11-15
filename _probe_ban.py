import sqlite3
from pathlib import Path
c = sqlite3.connect("data/checkapp.db")
c.row_factory = sqlite3.Row
print("signage", c.execute("select count(*) from signage").fetchone()[0])
cols = [x[1] for x in c.execute("pragma table_info(signage)").fetchall()]
print("cols", cols)
for r in c.execute("select * from signage order by id desc limit 5"):
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, str) and len(v) > 100:
            d[k] = v[:100] + "..."
    print(d)
print("uploads", list(Path("data/uploads").glob("*"))[:20] if Path("data/uploads").exists() else None)
print("bans")
for r in c.execute("select id, steam_id, reason, active from bans order by id desc limit 5"):
    print(dict(r))
