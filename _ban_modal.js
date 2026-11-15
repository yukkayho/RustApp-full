const fs = require("fs");
const t = fs.readFileSync("assets/index-CtjlL1Yw.js", "utf8");
const i = t.indexOf('__name:"BanCreateModal"');
fs.writeFileSync("_ban_modal.txt", t.slice(i, i + 4500));
console.log("wrote modal len", 4500);
// also find .player.ban( usage
let idx = 0, n = 0;
const hits = [];
while (n < 20) {
  const j = t.indexOf("player.ban", idx);
  if (j < 0) break;
  hits.push(t.slice(j - 120, j + 300));
  idx = j + 1;
  n++;
}
fs.writeFileSync("_ban_calls.txt", hits.join("\n\n====\n\n"));
console.log("calls", hits.length);
