import urllib.request, json, sqlite3

def get(p):
    r = urllib.request.Request(
        "http://127.0.0.1:8081" + p,
        headers={"Accept": "application/json", "X-Checkapp-Project": "crystalrust"},
    )
    return json.loads(urllib.request.urlopen(r, timeout=5).read())

c = sqlite3.connect(r"C:\Users\vovam\Desktop\сайт\site\data\checkapp.db")
c.row_factory = sqlite3.Row
print("=== alerts DB ===")
for r in c.execute("SELECT id,type,steam_id,substr(payload,1,80) p FROM alerts ORDER BY id DESC LIMIT 20"):
    print(dict(r))
print("=== alerts API ===")
a = get("/player-alert/browse?limit=20")
for x in a.get("data") or []:
    m = x.get("meta") or {}
    print(
        x.get("id"),
        x.get("type"),
        "msg=",
        str(m.get("message") or "")[:40],
        "bans=",
        len(m.get("bans") or []) if isinstance(m.get("bans"), list) else None,
        "mv=",
        bool(m.get("meta_value")),
    )
print("=== mutes ===")
for r in c.execute("SELECT id,steam_id,active,reason FROM mutes ORDER BY id DESC LIMIT 8"):
    print(dict(r))
print("=== chat ===")
for r in c.execute("SELECT id,steam_id,from_site,substr(text,1,50) t FROM chat ORDER BY id DESC LIMIT 10"):
    print(dict(r))
