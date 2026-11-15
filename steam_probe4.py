import re
s = open(r"assets\index-map-avatars.js", encoding="utf-8", errors="replace").read()
for needle in ["steamValidate(", "steam_query", "steamConnectStart", "integrations-connect-steam"]:
    hits = [m.start() for m in re.finditer(re.escape(needle), s)]
    print("=== %s : %d hits ===" % (needle, len(hits)))
    for i in hits[:6]:
        seg = s[max(0, i-500):i+500].replace("\n", " ")
        print("   ..." + seg + "...\n   ---")
