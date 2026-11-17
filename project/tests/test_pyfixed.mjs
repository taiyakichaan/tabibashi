// Python の f"{x:.nf}" / f"{x:.0%}" と同じ文字列になるか（半分ちょうどの偶数丸め）
import { readFileSync } from "node:fs";
import { pyFixed, pyPct0 } from "../site/js/recommend.js";
const C = JSON.parse(readFileSync(new URL("./pyfixed_cases.json", import.meta.url), "utf-8"));
let ng = 0;
for (const [x, n, want] of C) { const got = n === "pct" ? pyPct0(x) : pyFixed(x, n); if (got !== want) { ng++; console.log("NG", x, n, want, got); } }
console.log(`pyFixed: ${C.length}件  不一致=${ng}`); process.exit(ng ? 1 : 0);
