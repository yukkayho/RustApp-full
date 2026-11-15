s = open(
    r"c:\Users\vovam\Desktop\Checkapp\127.0.0.1_8081\rustapp.io\assets\index-CtjlL1Yw.js",
    encoding="utf-8",
    errors="replace",
).read()
chunks = []
for n in ["/server/pair", "/plugin/pair", "ca.pair", "generatePair", "pairCode", "pairing"]:
    i = 0
    found = 0
    while found < 3:
        j = s.find(n, i)
        if j < 0:
            break
        chunks.append(f"\n===== {n} @ {j} =====\n")
        chunks.append(s[max(0, j - 220) : j + 450])
        i = j + len(n)
        found += 1
open(
    r"c:\Users\vovam\Desktop\Checkapp\127.0.0.1_8081\rustapp.io\_pair_snip.txt",
    "w",
    encoding="utf-8",
).write("".join(chunks))
print("ok", len(chunks))
