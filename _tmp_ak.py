# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
t = open(r"c:\Users\vovam\Desktop\Checkapp\127.0.0.1_8081\rustapp.io\assets\index-CtjlL1Yw.js", encoding="utf-8", errors="ignore").read()
for pat in ["autokick-tab", "AutoKick", "autokick-localize", "AutokickModal", "autokick-modal", "court-autokick"]:
    print(pat, t.find(pat), t.count(pat))
i = t.find("autokick-tab-confirm")
if i >= 0:
    print(t[i-500:i+800])
