from pathlib import Path
import re
t = Path(r"C:\Users\vovam\Desktop\сайт\site\assets\index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")

# Find how access_token is set after login
for pat in [
    r"access_token\s*[:=].{0,120}",
    r"classicSignIn.{0,400}",
    r"setItem\([\"']access_token[\"'].{0,80}",
    r"signInSuccess|afterSignIn|onSignIn|loginSuccess.{0,200}",
    r"Bearer \$\{.{0,80}",
]:
    ms = list(re.finditer(pat, t))
    print("===", pat, "count", len(ms))
    for m in ms[:5]:
        print(m.group(0)[:350])
        print("---")
