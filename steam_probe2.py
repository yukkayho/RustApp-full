import re
s = open(r"assets\index-map-avatars.js", encoding="utf-8", errors="replace").read()
for needle in ["steamSignUp(", "steamLink(", "steamValidate("]:
    hits = [m.start() for m in re.finditer(re.escape(needle), s)]
    print("=== %s : %d ===" % (needle, len(hits)))
    for i in hits[:6]:
        seg = s[max(0, i-450):i+250].replace("\n", " ")
        print("   ..." + seg + "...\n   ---")
