import re
p = r"assets\index-map-avatars.js"
s = open(p, encoding="utf-8", errors="replace").read()
for needle in ["steam/sign-up", "steamcommunity.com/login", "openid.return_to", "auth/steam"]:
    idxs = [m.start() for m in re.finditer(re.escape(needle), s)][:4]
    print("=== %s : %d hits ===" % (needle, len(idxs)))
    for i in idxs:
        print("   ..." + s[max(0, i-500):i+300].replace("\n", " ") + "...")
        print("   ---")
