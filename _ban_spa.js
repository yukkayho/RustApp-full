const fs = require("fs");
const t = fs.readFileSync("assets/index-CtjlL1Yw.js", "utf8");
const out = [];
out.push("post /ban count " + (t.split('"/ban"').length - 1));
let idx = 0;
let n = 0;
while (n < 15) {
  const i = t.indexOf(".post(", idx);
  if (i < 0) break;
  const snip = t.slice(i, i + 120);
  if (/ban/i.test(snip)) out.push(snip);
  idx = i + 1;
  n++;
}
// find ban create modal / finish
for (const key of ["ban-create", "BanCreate", "createBan", "finish-ban", "override_broadcast", "steamId"]) {
  out.push(key + " => " + (t.split(key).length - 1));
}
const i = t.indexOf("override_broadcast");
out.push("\n=== override_broadcast ===\n" + t.slice(i - 300, i + 500));
const j = t.indexOf('__name:"ban.');
out.push("\n=== ban. component ===\n" + t.slice(j, j + 800));
// find axios ban service
const k = t.indexOf("createBan");
out.push("\n=== createBan ===\n" + t.slice(Math.max(0, k - 200), k + 400));
const m = t.indexOf('post("/ban"');
out.push("\n=== post ban ===\n" + t.slice(m - 100, m + 250));
const p = t.indexOf("signage/browse");
out.push("\n=== signage browse ===\n" + t.slice(p - 150, p + 400));
fs.writeFileSync("_ban_spa.txt", out.join("\n"));
console.log("wrote", out.length);
