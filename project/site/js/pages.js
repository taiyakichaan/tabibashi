// 入力によって中身が変わるページ（結果・お気に入り・検索・スポットごとのホテル）の HTML を組み立てる。
// app.py の _recommend() / compare_html() / fav_page() / search_page() / search_all() / hotel_page() と同じ文字列を作る。
// スポットの行（spot_row）は、書き出し済みのエリアページの HTML から取り出して使う（行の中身は i・extra 以外は同じ）。
import { pyFixed, pyPct0, makeFx } from "./recommend.js";

// サイトのルート。ドメイン直下なら "/"、GitHub Pages の「ユーザー名.github.io/リポジトリ名/」なら "/リポジトリ名/"。
// 書き出した HTML の画像・データは "/images/…" "/data/…"（ルートからの絶対パス）なので、サブフォルダで公開したときは付け替える。
export const BASE = new URL("../", import.meta.url).pathname;
export const withBase = (h) => (BASE === "/" ? h : h.replace(/(["'(]|&quot;)\/(images|data)\//g, `$1${BASE}$2/`));

// ---------- Python の html.escape / json.dumps / kb() と同じもの ----------
export const pyEsc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[c]);
export const pyUnesc = (s) => String(s).replace(/&(amp|lt|gt|quot|#x27|#39);/g, (m, k) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#x27": "'", "#39": "'" })[k]);
export const fmtPy = (s, o) => s.replace(/\{(\w+)\}/g, (m, k) => (k in o ? String(o[k]) : m));
const jsgo = (...parts) => pyEsc(`tjNav(${JSON.stringify(parts.join("\t"))});return false;`);

// brk.kb: HTML の本文だけ、句点のあとに <br> を入れる
const KB_SKIP = ["script", "style", "select", "option", "textarea", "title", "svg"];
const KB_BLOCK = ["</", "<br", "<p", "<div", "<ul", "<ol", "<li", "<h", "<table", "<section", "<dl", "<dd", "<dt", "<details", "<nav"];
export function kb(s) {
  if (!s || !s.includes("。")) return s;
  const parts = s.split(/(<[^>]*>)/), n = parts.length, out = [];
  let skip = null;
  for (let i = 0; i < n; i++) {
    const p = parts[i];
    if (i % 2) {
      const low = p.slice(1, 12).toLowerCase();
      if (skip) { if (low.startsWith("/" + skip)) skip = null; }
      else for (const t of KB_SKIP) if (low.startsWith(t) && !p.endsWith("/>")) { skip = t; break; }
      out.push(p); continue;
    }
    if (skip || !p.includes("。")) { out.push(p); continue; }
    const nxt = i + 1 < n ? parts[i + 1].toLowerCase() : "";
    let p2 = p.replace(/。(?![\s）」』\)】〉]|$)/g, "。<br>");
    if (p.endsWith("。") && nxt && !KB_BLOCK.some((x) => nxt.startsWith(x))) p2 += "<br>";
    out.push(p2);
  }
  return out.join("");
}

// ---------- 書き出し済みページの読み込み ----------
const PAGE = new Map();
export function loadPage(lang, name) {
  const k = `${lang}/${name}`;
  if (!PAGE.has(k)) PAGE.set(k, fetch(`${BASE}data/pages/${k}.html`).then((r) => { if (!r.ok) throw new Error(k + " " + r.status); return r.text(); }));
  return PAGE.get(k);
}
const JSONS = new Map();
export const loadJson = (p) => { if (!JSONS.has(p)) JSONS.set(p, fetch(p).then((r) => r.json())); return JSONS.get(p); };

// エリアページの HTML からスポットの行を取り出す（文字列のまま。ブラウザの再シリアライズで中身が変わらないように）
const ROWS = new Map();
const ROW_END = 'onclick="event.stopPropagation();tjFav(this)">★</button></div>';
export async function regionRows(lang, COMMON, reg) {
  const k = `${lang}/${reg}`;
  if (ROWS.has(k)) return ROWS.get(k);
  const html = await loadPage(lang, `region-${COMMON.regions[reg].id}`), map = new Map();
  let pos = 0;
  for (;;) {
    const a = html.indexOf('<div class="spot" data-off=', pos); if (a < 0) break;
    const b = html.indexOf(ROW_END, a); if (b < 0) break;
    const row = html.slice(a, b + ROW_END.length); pos = b + ROW_END.length;
    const sp = /class="star" data-reg="[^"]*" data-sp="([^"]*)"/.exec(row);
    if (sp) { const name = pyUnesc(sp[1]); if (!map.has(name)) map.set(name, row); }
  }
  ROWS.set(k, map);
  return map;
}
// spot_row(..., i, show_reg, extra) と同じ行にする
export function rowAs(row, i, insert = "") {
  let r = row.replace(/ data-i="\d+">/, ` data-i="${i}">`);
  if (insert) { const j = r.indexOf('<span class="sd">'); r = r.slice(0, j) + insert + r.slice(j); }
  return r;
}

// エリアページ: 「今月」の印を今日の月に付け直す（書き出し時の月のままにならないように）
export function fixMonth(root, month) {
  root.querySelectorAll(".season .mrow").forEach((row) => {
    row.querySelectorAll(":scope > i").forEach((cell, k) => { cell.className = `${cell.classList.contains("on") ? "on" : ""}${k + 1 === month ? " now" : ""}`; });
  });
}

// ---------- guide.py lux_head / lux_sec / lux_page ----------
export function luxHead(kicker, title, lead = "", ways = [], sub = "") {
  const li = ways.map(([sid, x], i) => `<li><a href="#" class="p2way" onclick="var e=document.getElementById('${sid}');if(e)e.scrollIntoView({behavior:'smooth',block:'start'});return false"><b>${i + 1}</b>${x}</a></li>`).join("");
  return `<div class="p2title luxt"><div class="p2country"><i></i><span>${kicker}</span><i></i></div>${sub ? `<div class=luxk>${sub}</div>` : ""}<h1>${title}</h1><i></i>`
    + `${lead ? `<p class=p2lead>${lead}</p>` : ""}${li ? `<ol class=p2ways>${li}</ol>` : ""}</div>`;
}
export const luxSec = (i, sid, title, desc, body, right = "", cls = "") =>
  `<section class="luxsec ${cls}" id="${sid}"><div class="numhead"><b>${i}</b><div><h3>${title}</h3>${desc ? `<p>${desc}</p>` : ""}</div>${right ? `<span class=nhx>${right}</span>` : ""}</div><div class="luxbody">${body}</div></section>`;
export const luxPage = (cls, head, secs, foot = "", attrs = "") => `<div class="pg lux ${cls}" ${attrs}>${head}<div class="luxframe">${secs.join("")}${foot}</div></div>`;

// ---------- ③ 結果（app.py _recommend + compare_html + feat_text） ----------
export function featText(f, row, inp, t, Ln, meta) {
  const FX = makeFx(meta.FX);
  if (f === "trip_days") return fmtPy(t.why_days, { n: Math.trunc(row[f]) });
  if (f === "budget_per_day") { const c = FX.curOf(inp.lang, inp.cur); return fmtPy(t.why_budget, { n: FX.fmt(FX.conv(Math.expm1(row[f]), meta.FX.BASE[inp.m], c), c) }); }
  if (f === "party_type") return fmtPy(t.why_party, { p: Ln.party[row[f]] });
  if (f === "first_visit") return Math.trunc(row[f]) ? t.why_first : t.why_repeat;
  const inv = Object.fromEntries(Object.entries(meta.KEYS).map(([k, v]) => [v, k]));
  const k = f.endsWith("_interest") ? f.slice(0, -9) : inv[f];
  return `${t.sl[k]} ${Math.trunc(row[f])}/5`;
}
export async function resultHtml(R, inp, ctx) {
  const { COMMON, Ln, meta, v, month } = ctx, m = inp.m, lang = inp.lang, t = Ln.m[m].tx, FX = makeFx(meta.FX), cu = FX.curOf(lang, inp.cur);
  const rowsAll = await Promise.all(R.top5.map((r) => regionRows(lang, COMMON, r.region)));
  const out = [`<div class="hd">${t.res}</div><div class="regions">`];
  R.top5.forEach((r, k) => {
    const i = k + 1, reg = r.region, rmap = rowsAll[k];
    const rows = r.spots.map((s, j) => rowAs(rmap.get(s.spot), j)).join("");
    const why = r.why.map((w) => `<li>${pyEsc(featText(w.feat, R.row, inp, t, Ln, meta))}<b>${w.pt}</b></li>`).join("") || `<li class="none">${t.why_none}</li>`;
    const ph = COMMON.regions[reg];
    const cover = ph.photo ? `background-image:url('${ph.photo}');${ph.pos}` : `background-image:url('${COMMON.cover_svg[m][i - 1]}')`;
    out.push(`<div class="rw"><div class="region" role="link" tabindex="0" onclick="${jsgo("region", reg)}"><div class="cover" style="${cover}"><div class="rank">${i}</div><div><div class="name">${pyEsc(Ln.rname[reg])}</div>`
      + `<div class="pct">${r.pct}<small>${t.match}</small></div></div></div><div class="spots"><div class="whym"><span>${t.why_title}</span><ul>${why}</ul></div>${rows}<div class="more">${t.allspots}（${r.n_spots}）→</div></div></div></div>`);
  });
  out.push("</div>");
  const enc = (x) => encodeURIComponent(String(x)).replace(/%20/g, "+");
  const q = { m, d: Math.trunc(inp.days), b: Math.trunc(+inp.budget || 0), c: cu, p: inp.party, f: R.x.first ? 1 : 0, s: inp.scores.map((x) => Math.trunc(x)).join(","), l: lang, v };
  const qs = "?" + Object.entries(q).map(([k, x]) => `${k}=${enc(x)}`).join("&");
  out.push(`<i id="tjq" hidden data-q="${pyEsc(qs)}"></i>`);
  out.push(`<div class="share"><button type="button" data-ok="${pyEsc(t.copied)}" onclick="${pyEsc(`tjCopy(${JSON.stringify(qs)},this)`)}">${t.share}</button><small>${t.share_hint}</small></div>`);
  out.push(`${Ln.m[m].model_note}${Ln.m[m].note}`);
  const bmax = Math.max(...R.blocks.map((b) => b.value));
  const bars = R.blocks.map((b) => `<div class="bar"><span class="l">${pyEsc(Ln.bname[m][b.block])}</span><span class="t"><span class="f" style="width:${b.width}%"></span></span><span class="v">${b.pct}</span></div>`).join("");
  const cols = R.top5.slice(0, 3).map((r) => {
    const mon = COMMON.regions[r.region].months;
    return `<div class="cmpc"><b>${pyEsc(Ln.rname[r.region])}</b><span class="p">${r.pct}</span>`
      + `<dl><dt>${t.cmp_spots}</dt><dd>${r.n_spots}</dd><dt>${t.cmp_season}</dt><dd>${Ln.season_rng[r.region] || "–"}</dd>`
      + `<dt>${fmtPy(t.cmp_now, { m: month })}</dt><dd>${mon.includes(month) ? "◎" : "–"}</dd></dl></div>`;
  }).join("");
  const side = `<div class="cmp2"><h3>${t.cmp_title}</h3><div class="cmpg">${cols}</div></div>` + `<div class="blk blk2"><h3>${t.blk}</h3>${bars}</div>`;
  void bmax;
  return [kb(out.join("")), kb(side)];
}

// ---------- お気に入り・旅程（app.py fav_page + set_favs の検証） ----------
export function cleanFavs(raw, COMMON) {
  const out = [], seen = new Set();
  for (const x of Array.isArray(raw) ? raw : []) {
    if (!Array.isArray(x) || x.length !== 2 || typeof x[0] !== "string" || typeof x[1] !== "string" || !COMMON.regions[x[0]]) continue;
    const k = x[0] + "\t" + x[1]; if (seen.has(k)) continue; seen.add(k); out.push([x[0], x[1]]);
  }
  return out.slice(0, 300);
}
export async function favHtml(m, lang, favs, ctx) {
  const { COMMON, Ln } = ctx, t = Ln.m[m].tx, L = Ln.lbl_plan, X = Ln.favx, ea = pyEsc;
  const groups = new Map();
  for (const [reg, sp] of favs) { if (!groups.has(reg)) groups.set(reg, []); groups.get(reg).push(sp); }
  const maps = await Promise.all([...groups.keys()].map((reg) => regionRows(lang, COMMON, reg)));
  const secs = []; let nAll = 0, gi = 0;
  for (const [reg, sps] of groups) {
    const rmap = maps[gi++], rows = [], rn = Ln.rname[reg];
    sps.forEach((sp, j) => {
      const row = rmap.get(sp); if (!row) return;
      const ex = `<div class="plx"><select class="daysel" data-reg="${ea(reg)}" data-sp="${ea(sp)}" data-rn="${ea(rn)}" aria-label="${L.plan_dayhd}" onchange="tjPlanSet(this)"></select>`
        + `<label class="tm">${L.plan_time}<input type="time" class="tmsel" data-reg="${ea(reg)}" data-sp="${ea(sp)}" onchange="tjPlanSet(this)"></label></div>`;
      rows.push(rowAs(row, j, ex));
    });
    if (!rows.length) continue;
    nAll += rows.length;
    const R = COMMON.regions[reg], th = R.photo ? `<img class="favth" src="${R.photo}" alt="" loading="lazy" style="object-position:${R.focus[0]}% ${R.focus[1]}%">` : "";
    secs.push(`<section class="cat favg"><h3 data-rg="${ea(rn)}">${th}<span class="favrn"><small>${Ln.cn[R.m]}</small>${pyEsc(rn)}</span>`
      + `<em>${fmtPy(t.cnt, { n: rows.length })}</em></h3><div class="spots">${rows.join("")}</div></section>`);
  }
  if (!secs.length) return Ln.m[m].fav_empty_page;
  const top = `<div class="plantop"><label>${L.plan_start}<input type="date" id="plan-start" onchange="tjPlanSet(this)"></label>`
    + `<label>${L.plan_days}<input type="number" id="plan-days" min="1" max="14" onchange="tjPlanSet(this)"></label>`
    + `<button type="button" class="pri" onclick="tjPlanIcs()">${L.plan_ics}</button><button type="button" onclick="window.print()">${L.plan_pdf}</button>`
    + `<button type="button" data-ok="${ea(t.copied)}" onclick="tjPlanText(this)">${L.plan_copy}</button><button type="button" onclick="tjFavClear()">${t.fav_clear}</button><span id="planmsg"></span></div>`;
  const attrs = Object.entries({ lang, day: L.plan_day, none: L.plan_none, needdate: L.plan_needdate, un: L.plan_un, route: L.plan_route, emptysched: L.plan_empty_sched, note: L.plan_note, sched: L.plan_sched })
    .map(([k, v]) => `data-${k}="${ea(v)}"`).join(" ");
  const ways = [["fav-plan", X.s1], ["fav-spots", fmtPy(X.w2, { n: nAll })], ["fav-sched", X.s3]];
  const head = luxHead(X.k, t.fav_title, t.fav_sub, ways);
  const body = [luxSec(1, "fav-plan", X.s1, X.d1, top), luxSec(2, "fav-spots", X.s2, L.plan_hint, secs.join(""), fmtPy(t.cnt, { n: nAll })),
    luxSec(3, "fav-sched", X.s3, X.d3, '<div class="planout" id="planout"></div>')];
  return kb(luxPage("planner favpg", head, body, "", attrs));
}

// ---------- 検索（app.py norm / search_all / search_page） ----------
let SEARCH = null;
// unicodedata.normalize("NFKC", s).casefold().translate(VAR)。casefold は toLowerCase に、大文字小文字以外で違う文字だけ足す
const FOLD = { "ß": "ss", "ẞ": "ss", "ς": "σ", "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "ŉ": "ʼn", "ſ": "s" };
export function norm(s, VAR) {
  let x = String(s).normalize("NFKC").toLowerCase().replace(/[ßẞςﬀ-ﬆŉſ]/g, (c) => FOLD[c] || c);
  return [...x].map((c) => (c in VAR ? VAR[c] : c)).join("");
}
export async function searchHtml(m, lang, q, ctx) {
  const { COMMON, Ln } = ctx, t = Ln.m[m].tx, S = Ln.srch, OTHER = { taiwan: "japan", japan: "taiwan" };
  SEARCH ||= await loadJson(`${BASE}data/search.json`);
  const nq = norm(q, SEARCH.var).trim(), li = { ja: 0, zh: 1, en: 2 }[lang], hits = [];
  if (nq) {
    for (const [em, reg, rn, cats, spots] of SEARCH.idx) {
      const rhit = rn.some((x) => x.includes(nq)) || SEARCH.cwords[em].includes(nq);
      const shits = spots.filter(([s, ns]) => ns.includes(nq)).map(([s]) => s);
      const chits = cats.filter((c) => SEARCH.catn[c][li].includes(nq));
      if (rhit || shits.length || chits.length) hits.push({ e: { m: em, reg }, rhit, shits, chits });
    }
    const key = (h) => [h.e.m !== m ? 1 : 0, h.rhit ? 0 : 1, -h.shits.length];
    hits.sort((a, b) => { const x = key(a), y = key(b); for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i]; return a.e.reg < b.e.reg ? -1 : a.e.reg > b.e.reg ? 1 : 0; });
  }
  const qh = pyEsc(q), title = lang !== "en" ? `${t.sres}<span class="luxq">「${qh}」</span>` : `${t.sres}<span class="luxq">“${qh}”</span>`;
  if (!hits.length) return kb(luxPage("srch", luxHead(S[0], title, S[5]), [`<div class="luxbody"><div class="res-empty">${t.nores}</div></div>`]));
  const nsp = hits.reduce((n, h) => n + h.shits.length, 0), secs = [], ways = [];
  for (const mk of [m, OTHER[m]]) {
    const hs = hits.filter((h) => h.e.m === mk); if (!hs.length) continue;
    const cards = hs.map(({ e, rhit, shits, chits }) => {
      const why = [];
      if (rhit) why.push(`<b>${t.why_region}</b>`);
      if (chits.length) why.push(`<b>${t.why_cat}</b>` + chits.map((c) => Ln.catname[c]).join(", "));
      if (shits.length) why.push(`<b>${t.why_spot}</b>` + shits.slice(0, 4).map(pyEsc).join("、") + (shits.length > 4 ? ` ${fmtPy(t.andmore, { n: shits.length - 4 })}` : ""));
      const R = COMMON.regions[e.reg], go = jsgo("region", e.reg);
      return `<div class="hit hitx" role="link" tabindex="0" onclick="${go}" onkeydown="if(event.key==='Enter'){${go}}"><img src="${R.photo}" alt="" loading="lazy" decoding="async" style="object-position:${R.focus[0]}% ${R.focus[1]}%">`
        + `<div class="hitin"><div class="cn">${Ln.cn[mk]}</div><h4>${pyEsc(Ln.rname[e.reg])}</h4><div class="why">${why.map((w) => `<p>${w}</p>`).join("")}</div></div><span class="hgo" aria-hidden="true">&#8594;</span></div>`;
    });
    const sid = `srch-${mk}`, ttl = `${S[1]} — ${Ln.cn[mk]}`;
    ways.push([sid, `${ttl}（${hs.length}）`]);
    secs.push(luxSec(secs.length + 1, sid, ttl, S[2], `<div class="hitgrid">${cards.join("")}</div>`, fmtPy(S[4], { n: hs.length })));
  }
  const want = []; let nrows = 0;                     // 先頭80件だけ行を作る
  for (const h of hits) for (const s of h.shits) { nrows++; if (want.length < 80) want.push([h.e.reg, s]); }
  const maps = new Map();
  await Promise.all([...new Set(want.map((w) => w[0]))].map(async (reg) => maps.set(reg, await regionRows(lang, COMMON, reg))));
  const rows = want.map(([reg, s]) => { const r = maps.get(reg).get(s); return r ? rowAs(r, 0, `<small class="rg">${pyEsc(Ln.rname[reg])}</small>`) : ""; }).filter(Boolean);
  if (rows.length) {
    ways.push(["srch-spots", `${t.sec_spots}（${nrows}）`]);
    secs.push(luxSec(secs.length + 1, "srch-spots", t.sec_spots, S[3], `<div class="spots">${rows.join("")}</div>`, fmtPy(S[4], { n: nrows })));
  }
  return kb(luxPage("srch", luxHead(S[0], title, fmtPy(t.pagesfound, { p: hits.length, s: nsp }), ways), secs));
}

// ---------- ⑤ スポットのホテル予約サイト（app.py hotel_page のひな形に差し込む） ----------
export async function hotelHtml(m, lang, reg, spot, ctx) {
  const { Ln } = ctx, terms = await loadJson(`${BASE}data/hotel_terms_${m}.json`);
  const [term, qu, qe] = (terms[reg] && terms[reg][spot]) || [reg, encodeURIComponent(reg), encodeURIComponent(reg)];
  const rn = pyEsc(Ln.rname[reg]);
  const h = Ln.hotel_tpl[m].replace(/\x01|\x06/g, rn).replace(/\x02/g, pyEsc(spot)).replace(/\x03/g, pyEsc(term)).replace(/\x04/g, qu).replace(/\x05/g, qe);
  return kb(h);
}
