// JS版の推薦結果が Python版（tests/golden.json）と一致するかを確かめる。
// 使い方: node tests/test_recommend.mjs   （終了コード 0 = 全件一致）
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { loadAll, recommend, makeFx } from "../site/js/recommend.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const getJson = async (p) => JSON.parse(readFileSync(join(root, "site", p), "utf-8"));
const DB = await loadAll(getJson);
const G = JSON.parse(readFileSync(join(root, "tests", "golden.json"), "utf-8"));
const TOL = 1e-9;

let fails = 0, maxProb = 0, maxDelta = 0, maxBlock = 0;
const fail = (i, what, a, b) => { if (fails++ < 20) console.log(`NG case#${i} ${what}\n  python: ${JSON.stringify(a)}\n  js    : ${JSON.stringify(b)}`); };
const near = (a, b) => Math.abs(a - b) <= TOL;

G.cases.forEach(({ input, expected: E }, i) => {
  const R = recommend(DB, input);
  if (!near(R.x.budget_log, E.x.budget_log)) fail(i, "budget_log", E.x.budget_log, R.x.budget_log);
  E.proba.forEach((p, k) => { maxProb = Math.max(maxProb, Math.abs(p - R.proba[k]), Math.abs(E.proba_model[k] - R.proba_model[k])); });
  if (JSON.stringify(R.ranking) !== JSON.stringify(E.ranking)) fail(i, "地域の順位（全体）", E.ranking, R.ranking);
  E.top5.forEach((e, j) => {
    const r = R.top5[j];
    if (!r || r.region !== e.region) return fail(i, `Top${j + 1} 地域`, e.region, r && r.region);
    if (r.pct !== e.pct) fail(i, `Top${j + 1} 一致度%`, e.pct, r.pct);
    if (r.n_spots !== e.n_spots) fail(i, `Top${j + 1} スポット数`, e.n_spots, r.n_spots);
    const es = e.spots.map((s) => s.spot), rs = r.spots.map((s) => s.spot);
    if (JSON.stringify(es) !== JSON.stringify(rs)) fail(i, `Top${j + 1} スポット順`, es, rs);
    e.spots.forEach((s, q) => { if (r.spots[q] && r.spots[q].match !== s.match) fail(i, `Top${j + 1} match`, s.match, r.spots[q].match); });
    const ew = e.why.map((w) => w.feat + " " + w.pt), rw = r.why.map((w) => w.feat + " " + w.pt);
    if (JSON.stringify(ew) !== JSON.stringify(rw)) fail(i, `Top${j + 1} おすすめの理由`, ew, rw);
    e.why.forEach((w, q) => r.why[q] && (maxDelta = Math.max(maxDelta, Math.abs(w.delta - r.why[q].delta))));
  });
  const eb = E.blocks.map((b) => `${b.block} ${b.pct} ${b.width}`), rb = R.blocks.map((b) => `${b.block} ${b.pct} ${b.width}`);
  if (JSON.stringify(eb) !== JSON.stringify(rb)) fail(i, "ブロック別", eb, rb);
  E.blocks.forEach((b, q) => R.blocks[q] && (maxBlock = Math.max(maxBlock, Math.abs(b.value - R.blocks[q].value))));
});

const fx = makeFx(DB.meta.FX);
let fxFails = 0;
for (const c of G.fx) {
  const y = fx.conv(c.x, c.a, c.b);
  if (y !== c.conv || fx.nice(y, c.b) !== c.nice || fx.fmt(y, c.b) !== c.fmt) { if (fxFails++ < 10) console.log("NG fx", c, { conv: y, nice: fx.nice(y, c.b), fmt: fx.fmt(y, c.b) }); }
}
for (const [m, o] of Object.entries(G.default_budget)) for (const [c, v] of Object.entries(o)) if (fx.defaultBudget(m, c) !== v) { fxFails++; console.log("NG default_budget", m, c, v, fx.defaultBudget(m, c)); }

const ok = maxProb <= TOL && maxDelta <= TOL && maxBlock <= TOL && !fails && !fxFails;
console.log(`推薦: ${G.cases.length}ケース  不一致=${fails}`);
console.log(`  確率の最大差=${maxProb.toExponential(2)}  寄与度の最大差=${maxDelta.toExponential(2)}  ブロック合計の最大差=${maxBlock.toExponential(2)}  (許容 ${TOL})`);
console.log(`金額の換算・丸め・表記: ${G.fx.length}件  不一致=${fxFails}`);
console.log(ok ? "OK: Python版と一致" : "NG");
process.exit(ok ? 0 : 1);
