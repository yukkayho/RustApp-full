from pathlib import Path
import re

text = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
out = []

needles = [
    "payments.limits.clients", "limits.clients", "clients_limit", "clientsLimit",
    "clients_db", "clientsCount", "clients.count", "usage_failed",
    "tariff_project_usage", "plan-warning-clients", "client-limit-exceeded",
]
for needle in needles:
    j = 0
    shown = 0
    while shown < 3:
        i = text.find(needle, j)
        if i < 0:
            break
        out.append(f"==== {needle} @ {i} ====")
        out.append(text[max(0, i - 200) : i + 400].replace("\n", " "))
        out.append("")
        j = i + len(needle)
        shown += 1

for m in re.finditer(r'__name:"[^"]*(?:Payment|Billing|Tariff|Wallet|Plan)[^"]*"', text):
    out.append(f"comp {m.group()} @ {m.start()}")

# 10 near client in code half
for m in re.finditer(r".{0,50}client.{0,50}\b10\b.{0,50}|.{0,50}\b10\b.{0,50}client.{0,50}", text[1000000:], re.I):
    seg = m.group().replace("\n", " ")
    if "t:0,b:" in seg:
        continue
    out.append(f"10nearclient: {seg[:200]}")

Path("_search_staff_limit_out.txt").write_text("\n".join(out), encoding="utf-8")
print("lines", len(out))
