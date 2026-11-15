from pathlib import Path
import re

text = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
out = []

for needle in [
    "change-plan.limits.clients", "payments.limits.clients", "clients_db",
    "clients_limit", "clientsLimit", "getClientsV2", "ClientManageModal",
    "plan-warning-clients", "limits.clients",
]:
    j = 0
    n = 0
    while n < 5:
        i = text.find(needle, j)
        if i < 0:
            break
        out.append(f"==== {needle} @ char {i} ====")
        out.append(text[max(0, i - 250) : i + 500])
        out.append("")
        j = i + len(needle)
        n += 1

# servers_db pattern for comparison - find clients equivalent
for m in re.finditer(r"clients_db|servers_db|players_db", text):
    if m.group() == "clients_db":
        i = m.start()
        out.append(f"clients_db @ {i}: {text[max(0,i-100):i+200]}")

Path("_bundle_clients.txt").write_text("\n".join(out), encoding="utf-8")
print(len(out), "sections")
