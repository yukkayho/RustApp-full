from pathlib import Path
import re
t = Path(r"C:\Users\vovam\Desktop\сайт\site\assets\index-CtjlL1Yw.js").read_text(encoding="utf-8", errors="ignore")
for m in re.finditer(r"getMy:async\(\)=>.{0,120}", t):
    print(m.group(0))
