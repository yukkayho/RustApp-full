from pathlib import Path
import re
t = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
# Find CAt definition near meta.bans click
i = t.find("f(CAt)(n.value,a.meta.bans)")
print("click at", i)
# search BanList or openBans
for n in ["openBan", "BanList", "meta.bans)", "ban-view", "external_ban"]:
    print(n, t.count(n))
# Find function that opens bans modal - look backwards for CAt=
m = re.search(r"CAt=([A-Za-z0-9_$]+)", t)
print("CAt assign", m.group(0) if m else None)
# find modal bans list render with шт
j = t.find('" шт"')
if j < 0:
    j = t.find("шт.")
print("sht", j, t[max(0,j-200):j+150] if j>=0 else "")
# discord data keys check_start
for n in ["checkStart", "check_start", "onCheckStart", "started:!", "finished:!"]:
    idxs = [m.start() for m in re.finditer(n, t)][:2]
    print(n, idxs)
    for i in idxs:
        print(t[i:i+180][:180])
