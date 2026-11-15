from pathlib import Path
import re
t = Path(r"C:\Users\vovam\Desktop\сайт\site\assets\index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
for pat in [
    r".{0,80}access_token.{0,120}",
    r".{0,60}__checkappStats.{0,100}",
    r"classicSignIn:async.{0,200}",
    r"Qbt=.{0,200}",
]:
    ms = list(re.finditer(pat, t))
    print("===", pat, len(ms))
    for m in ms[:4]:
        print(m.group(0)[:220])
        print("---")
