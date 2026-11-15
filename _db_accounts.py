import sqlite3
c = sqlite3.connect("data/checkapp.db")
c.row_factory = sqlite3.Row
print("tables:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
for t in ("users", "sessions", "project", "servers", "pair_codes"):
    try:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n}")
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        print("  cols", cols)
        for r in c.execute(f"SELECT * FROM {t} LIMIT 8"):
            d = dict(r)
            for k in list(d):
                if any(x in k.lower() for x in ("pass", "token", "secret", "hash")):
                    d[k] = "***"
            print(" ", d)
    except Exception as e:
        print(t, e)
