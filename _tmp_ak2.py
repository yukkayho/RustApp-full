# -*- coding: utf-8 -*-
import sys,re
sys.stdout.reconfigure(encoding="utf-8")
t = open(r"c:\Users\vovam\Desktop\Checkapp\127.0.0.1_8081\rustapp.io\assets\index-CtjlL1Yw.js", encoding="utf-8", errors="ignore").read()
i = t.find("autokick-modal")
print("first at", i)
print(t[i:i+3500])
