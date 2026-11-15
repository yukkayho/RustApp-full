from pathlib import Path
text = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")

# change-plan limits UI block
i = text.find("change-plan.limits.players")
while i >= 0:
    print("=== change-plan.limits @", i, "===")
    print(text[i:i+2500])
    print()
    i = text.find("change-plan.limits", i+1)
    if i < 0 or i > 2170000:
        break

# search i18n for clients limit strings
for needle in ["limits.clients", "Сотрудник", "Staff"]:
    j = 0
    c = 0
    while c < 3:
        k = text.find(needle, j)
        if k < 0: break
        seg = text[k:k+120]
        if "amount" in seg or "10" in seg or "limit" in seg.lower():
            print(f"i18n {needle} @ {k}: {seg}")
        j = k + 1
        c += 1

# ClientManageModal invite - look for length/count checks
i = text.find("ClientManageModal")
print("\n=== invite flow ===")
print(text[i:i+3500])
