from pathlib import Path
s = Path(r"C:\Downloaded Web Sites\rustapp.io\assets\index-Boae7-Pf.js").read_text(encoding="utf-8", errors="ignore")
for needle in ["createWebHistory", "createWebHashHistory", "createRouter", "DomainSite", "location.href.replace", "https://${", "`https://"]:
    i = 0
    n = 0
    while n < 5:
        j = s.find(needle, i)
        if j < 0:
            break
        print("====", needle, j)
        print(s[j:j+180])
        print()
        i = j + len(needle)
        n += 1
