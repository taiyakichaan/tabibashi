// 旅行条件 → おすすめ地域 Top5 の計算（Python版 app.py の recommend() と同じ式・同じ順番）。
// ブラウザでも Node でも動く ES モジュール。HTML は作らず、結果を構造化して返す。
//
//   import { loadAll, recommend } from "./js/recommend.js";
//   const DB = await loadAll((path) => fetch(path).then((r) => r.json()));
//   const res = recommend(DB, { m: "taiwan", lang: "ja", days: 4, budget: 30000, cur: "USD",
//                               party: "couple", first: "first", scores: [3, 3, ...18個] });
//
// Python 版と結果を合わせるための約束ごと
//  - 並べ替えはすべて安定ソート（同点は元の順番）。Python 側も kind="stable"（tools/app_stable_sort.patch）。
//  - 合計の取り方を numpy / pandas に合わせる（np.sum = pairwise、groupby.sum = Kahan 補正）。
//  - 丸めは Python と同じ偶数丸め（round(2.5) = 2、f"{0.125:.2f}" = "0.12"）。

// ---------- データ読み込み ----------
export async function loadAll(getJson, base = "data/") {
  const meta = await getJson(base + "meta.json");
  const DB = { meta, markets: {} };
  for (const m of ["taiwan", "japan"]) {
    const [model, spots] = await Promise.all([getJson(`${base}model_${m}.json`), getJson(`${base}spots_${m}.json`)]);
    DB.markets[m] = prepareMarket(meta, m, model, spots);
  }
  return DB;
}

export function prepareMarket(meta, m, model, spots) {
  // 地域ごとのスポット（app.py: spots[spots.region == reg].drop_duplicates("spot")）
  const byRegion = new Map();
  for (const r of spots) {
    let g = byRegion.get(r.region);
    if (!g) byRegion.set(r.region, (g = { list: [], seen: new Set() }));
    if (g.seen.has(r.spot)) continue;
    g.seen.add(r.spot); g.list.push(r);
  }
  return { m, model, spots, byRegion, pop: meta.POP[m], base: meta.BASE_ROW[m], blocks: meta.BLOCKS[m] };
}

// ---------- Python 互換の数値処理 ----------
// np.sum（pairwise summation, 8並列の展開・ブロック128）
export function npSum(a, lo = 0, n = a.length - lo) {
  if (n < 8) { let s = -0; for (let i = 0; i < n; i++) s += a[lo + i]; return n ? s : 0; }
  if (n <= 128) {
    const r = [];
    for (let k = 0; k < 8; k++) r[k] = a[lo + k];
    let i = 8;
    for (; i < n - (n % 8); i += 8) for (let k = 0; k < 8; k++) r[k] += a[lo + i + k];
    let res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; i++) res += a[lo + i];
    return res;
  }
  let n2 = Math.floor(n / 2); n2 -= n2 % 8;
  return npSum(a, lo, n2) + npSum(a, lo + n2, n - n2);
}

// pandas groupby().sum()（Kahan 補正つき）
function kahanSum(vals) {
  let s = 0, c = 0;
  for (const v of vals) { const y = v - c, t = s + y; c = t - s - y; s = t; }
  return s;
}

// Python の round()（偶数丸め）
export function pyRound(x) {
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

// Python の f"{x:.{n}f}"。double の値を正確な10進数にしてから、ちょうど半分のときだけ偶数側へ丸める
// （JS の toFixed は半分ちょうどを常に切り上げるため、1.25 → "1.3" になる。Python は "1.2"）
export function pyFixed(x, n) {
  if (!isFinite(x) || Math.abs(x) >= 1e21) return String(x);
  const neg = x < 0 || Object.is(x, -0);
  const [ip, fp] = Math.abs(x).toFixed(100).split(".");    // 100桁あれば半分ちょうどかどうかを判定できる
  let digits = BigInt(ip + fp.slice(0, n));
  const rest = fp.slice(n);
  if (rest[0] > "5" || (rest[0] === "5" && (/[1-9]/.test(rest.slice(1)) || digits % 2n === 1n))) digits += 1n;
  let t = digits.toString().padStart(n + 1, "0");
  if (n > 0) t = t.slice(0, -n) + "." + t.slice(-n);
  return (neg ? "-" : "") + t;
}
export const pyPct0 = (x) => pyFixed(x * 100, 0) + "%";   // f"{x:.0%}"

// ---------- 通貨（fx.py） ----------
export function makeFx(FX) {
  const conv = (x, a, b) => Number(x) / FX.PER_USD[a] * FX.PER_USD[b];
  const curOf = (lang, cur = "USD") => ({ ja: "JPY", zh: "TWD" })[lang] || (cur === "USD" || cur === "EUR" ? cur : "USD");
  const nice = (x, c) => { const s = FX.STEP[c]; return Math.max(s, Math.trunc(pyRound(x / s)) * s); };
  const defaultBudget = (m, c) => nice(conv(FX.DEFAULT_BASE[m], FX.BASE[m], c), c);
  const fmt = (x, c) => {
    const n = Math.trunc(pyRound(x)).toLocaleString("en-US");
    return { JPY: `${n}円`, TWD: `NT$${n}`, USD: `$${n}`, EUR: `€${n}` }[c];
  };
  return { conv, curOf, nice, defaultBudget, fmt };
}

// ---------- モデル（OneHotEncoder + StandardScaler + LogisticRegression） ----------
function vectorize(model, row) {
  const x = model.onehot.categories.map((c) => (row[model.onehot.col] === c ? 1 : 0));   // handle_unknown="ignore"
  model.num_cols.forEach((c, i) => x.push((row[c] - model.mean[i]) / model.scale[i]));
  return x;
}
export function predictProba(model, row) {
  const x = vectorize(model, row);
  const z = model.coef.map((w, k) => { let s = 0; for (let j = 0; j < x.length; j++) s += x[j] * w[j]; return s + model.intercept[k]; });
  const mx = Math.max(...z);
  const e = z.map((v) => Math.exp(v - mx));
  const s = npSum(e);
  return e.map((v) => v / s);
}

const stableOrderDesc = (vals) => vals.map((v, i) => i).sort((a, b) => vals[b] - vals[a] || a - b);

// ---------- 推薦（app.py recommend() の数値部分） ----------
export function recommend(DB, inp) {
  const { meta } = DB, M = DB.markets[inp.m], model = M.model, fx = makeFx(meta.FX);
  const first = inp.first === true || inp.first === "first" || inp.first === 1;
  const cu = fx.curOf(inp.lang, inp.cur || "USD");
  const vals = {}; meta.ALL.forEach((k, i) => (vals[k] = inp.scores[i]));
  const row = {
    trip_days: inp.days,
    budget_per_day: Math.log1p(fx.conv(inp.budget || 0, cu, meta.FX.BASE[inp.m])),
    party_type: inp.party,
    first_visit: first ? 1 : 0,
  };
  for (const k of meta.ALL) row[meta.KEYS[k] || `${k}_interest`] = vals[k];
  const feats = model.feats, classes = model.classes;

  const pvRaw = predictProba(model, row);
  let pv = pvRaw;
  if (first) {                                     // 初めての旅行: 定番スポットの多いエリアを優先
    const w = pvRaw.map((p, k) => p * (1 + meta.FIRST_W * (M.pop[classes[k]] ?? 0)));
    const s = npSum(w); pv = w.map((v) => v / s);
  }
  const order = stableOrderDesc(pv);
  const ranking = order.map((k) => classes[k]);

  // 寄与度: 各条件を「平均的な旅行者」の値に置き換えると一致度がどれだけ下がるか
  const delta = feats.map((f) => { const r2 = { ...row, [f]: M.base[f] }; const q = predictProba(model, r2); return pv.map((v, k) => v - q[k]); });

  const pref = meta.SPOT_COLS.map((k) => vals[k]);
  const top5 = order.slice(0, 5).map((k) => {
    const reg = classes[k], pr = pv[k];
    const all = M.byRegion.get(reg)?.list || [];
    const scored = all.map((r) => {
      let s = 0; meta.SPOT_COLS.forEach((c, j) => (s += r[c] * pref[j]));
      return { r, match: s + (r.tourism_value_score ?? 0) / 100 };
    });
    const spots = stableOrderDesc(scored.map((x) => x.match)).slice(0, 5).map((i) => ({ spot: scored[i].r.spot, match: scored[i].match, row: scored[i].r }));
    const c = delta.map((d) => d[k]);
    const why = stableOrderDesc(c).slice(0, 3).filter((j) => c[j] > 0.002)
      .map((j) => ({ feat: feats[j], delta: c[j], pt: `+${pyFixed(c[j] * 100, 1)}pt` }));
    return { region: reg, prob: pr, pct: pyPct0(pr), n_spots: all.length, spots, why };
  });

  // ブロック別の相性（p の並び順で、ブロック名の昇順にまとめて合計 → 大きい順）
  const groups = new Map();
  for (const k of order) { const b = M.blocks[classes[k]]; if (!groups.has(b)) groups.set(b, []); groups.get(b).push(pv[k]); }
  const keys = [...groups.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const sums = keys.map((b) => kahanSum(groups.get(b)));
  const bmax = Math.max(...sums);
  const blocks = stableOrderDesc(sums).map((i) => ({ block: keys[i], value: sums[i], pct: pyPct0(sums[i]), width: pyFixed(sums[i] / bmax * 100, 0) }));

  return { x: { budget_log: row.budget_per_day, first, cur: cu }, row, proba_model: pvRaw, proba: pv, ranking, top5, blocks };
}
