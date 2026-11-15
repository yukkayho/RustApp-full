const fs = require("fs");
const t = fs.readFileSync("assets/index-CtjlL1Yw.js", "utf8");
// find ban modal finish button flow
let i = t.indexOf("players/${W}/ban");
console.log(t.slice(i - 50, i + 200));
i = t.indexOf('ban:async');
console.log("\n---\n", t.slice(i, i + 150));
// BanCreate modal
i = t.indexOf("BanCreate");
console.log("\nBanCreate contexts:");
let idx = 0, n = 0;
while (n < 8) {
  const j = t.indexOf("BanCreate", idx);
  if (j < 0) break;
  console.log("\n@", j, t.slice(j - 80, j + 200));
  idx = j + 1;
  n++;
}
// find fulfilled ban toast / close modal
i = t.indexOf(".ban(");
console.log("\n.ban( calls:");
idx = 0; n = 0;
while (n < 10) {
  const j = t.indexOf(".ban(", idx);
  if (j < 0) break;
  const snip = t.slice(j - 100, j + 250);
  if (/players|BanCreate|modal|close|finish/i.test(snip)) console.log("\n", snip);
  idx = j + 1;
  n++;
}
