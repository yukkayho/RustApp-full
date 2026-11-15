import re
from pathlib import Path

text = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
needles = [
    "staff-limit",
    "staffLimit",
    "staff_limit",
    "clients_limit",
    "moderators",
    "limit:10",
    "limit===10",
    ">=10",
    ">10",
    "length>=10",
    "length>10",
    "10,staff",
    "staff,10",
    "employees",
    "client-limit",
    "clientLimit",
]
for needle in needles:
    j = 0
    shown = 0
    while shown < 4:
        i = text.find(needle, j)
        if i < 0:
            break
        chunk = text[max(0, i - 180) : i + 220]
        if "t:0,b:" in chunk and needle in ("employees", "moderators"):
            j = i + len(needle)
            continue
        print(f"\n==== {needle} @ {i} ====")
        print(chunk.replace("\n", " ")[:420])
        j = i + len(needle)
        shown += 1
