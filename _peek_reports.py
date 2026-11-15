from pathlib import Path
import re
t = Path("assets/index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
# find report table kd / toString usage near reports
for n in ["total_reports", "target_player", "kdr.toString", ".kd.toString", "reports.browse", "report.kd"]:
    print("===", n, t.count(n))
    for m in list(re.finditer(re.escape(n), t))[:2]:
        i = m.start()
        print(t[max(0,i-100):i+200].replace("\n"," ")[:350])
        print("---")

# find Cannot read / toString in report component context
idx = t.find("total_reports_unique")
print("\n=== around total_reports_unique ===")
print(t[max(0,idx-500):idx+800].replace("\n"," ")[:1200])
