// 画面の組み立てと画面遷移（元アプリの app.py の ui() / bridge_in() / on_load() をブラウザ側に移したもの）
//
// ・固定の HTML 部品（ヘッダーのメニュー・言語切替・使い方・見出し・地図・カテゴリ一覧・背景）は、
//   tools/export_ui.py が app.py の関数から書き出した data/ui_<言語>.json をそのまま使う。
// ・入力欄（スライダー等）は Gradio と同じ構造・クラス名の HTML をここで作る（見た目は css/gr.css + app.py の CSS）。
// ・部品の中の onclick="tjNav('…')" は、元アプリではサーバーへの通知だった。ここでは下の tjNav が受けて画面を切り替える。
import { loadAll, recommend, makeFx } from "./recommend.js";
import { attachTyphoons } from "./typhoon.js";
import { loadPage, fixMonth, resultHtml, favHtml, searchHtml, hotelHtml, cleanFavs, pyEsc, withBase } from "./pages.js";

const LAND = [["landing", null]];
const COND = [["landing", null], ["cond", null]];
const OTHER = { taiwan: "japan", japan: "taiwan" };

let COMMON = null;            // data/ui.json
const LANGS = {};             // data/ui_<lang>.json
let DB = null;                // 推薦用データ（初めて診断ボタンを押したときに読み込む）
let FX = null;

const S = { m: "taiwan", v: "pc", lang: "ja", hist: LAND.slice(), F: null, res: null };

// ---------- 小道具 ----------
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const getJson = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); });
async function lang(l) { return (LANGS[l] ||= await getJson(`data/ui_${l}.json`)); }
const L = () => LANGS[S.lang];
const T = (m = S.m) => L().m[m].tx;
const stage = () => S.hist[S.hist.length - 1][0];
const favs = () => { try { return cleanFavs(JSON.parse(localStorage.getItem("tj_favs") || "[]"), COMMON); } catch (e) { return []; } };
const mktOf = (reg) => COMMON.regions[reg].m;
const monthNow = () => new Date().getMonth() + 1;

function toast(msg) {
  let t = $(".tj-toast"); if (!t) { t = document.createElement("div"); t.className = "tj-toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg; clearTimeout(toast.tm); t.hidden = false; toast.tm = setTimeout(() => (t.hidden = true), 3200);
}
const FAIL = { ja: "ページを読み込めませんでした。通信状態を確認して、もう一度お試しください。", zh: "無法載入頁面，請確認網路連線後再試一次。", en: "Could not load the page. Check your connection and try again." };

// ---------- 入力欄の初期値（app.py ui() の reset=True と同じ） ----------
function defaultForm(m, l, cur = "USD") {
  const t = LANGS[l].m[m].tx;
  return { days: 4, party: "solo", first: "first", budget: t.bval, cur, scores: COMMON.all.map(() => 3), acc: false };
}

// ---------- Gradio と同じ構造の部品 ----------
// Gradio が各部品に付けるインラインスタイル（幅の比率・はみ出し・最小幅）も同じにする
const ST = {
  html: "border-style:solid;overflow:visible;min-width:min(0px,100%)",
  auto: "border-style:solid;overflow:auto;min-width:min(160px,100%)",       // スライダー・ラジオ
  hidden: "border-style:solid;overflow:hidden;min-width:min(160px,100%)",   // ドロップダウン・数値欄
  form: "flex-grow:0;min-width:min(0px,100%)",
  col: (g) => `flex-grow:${g};min-width:min(320px,100%)`,
};
const html = (id, inner, cls = "") =>
  `<div${id ? ` id="${id}"` : ""} class="block ${cls} hide-container auto-margin" style="${ST.html}"><div class="html-container"><div class="prose gradio-style ${cls}">${inner}</div></div></div>`;
const btn = (id, label, cls = "secondary", grow = 0) => `<button type="button" id="${id}" class="lg ${cls} gr-button"${grow ? ` style="flex-grow:${grow}"` : ""}>${esc(label)}</button>`;
const form = (inner) => `<div class="form" style="${ST.form}">${inner}</div>`;
// 元のページにある「見えない入力欄のまとまり」。高さ0だが列のすき間(16px)を1つ取るので、配置を合わせるために置く
const bridgeForm = () => form(`<div class="block hidden-bridge padded auto-margin" style="${ST.hidden}"></div>`);
const RESET_SVG = "↺";                                   // Gradio のリセットボタンと同じ文字
const CHEV_SVG = '<svg class="dropdown-arrow" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 18 18"><path d="M5 8l4 4 4-4z"></path></svg>';
const pct = (v, lo, hi) => `${((v - lo) / (hi - lo)) * 100}%`;
function slider(key, label, lo, hi, val, def) {
  return `<div class="block padded auto-margin gr-slider" data-k="${key}" data-def="${def}" style="${ST.auto}"><div class="wrap"><div class="head">`
    + `<label for="n-${key}"><span class="gr-title" data-testid="block-info">${esc(label)}</span></label>`
    + `<div class="tab-like-container"><input id="n-${key}" type="number" data-testid="number-input" min="${lo}" max="${hi}" step="1" value="${val}" aria-label="number input for ${esc(label)}">`
    + `<button type="button" class="reset-button" aria-label="Reset to default value" data-testid="reset-button">${RESET_SVG}</button></div></div>`
    + `<div class="slider_input_container"><span class="min_value" data-testid="min-value">${lo}</span>`
    + `<input type="range" data-testid="range-input" min="${lo}" max="${hi}" step="1" value="${val}" style="--range_progress:${pct(val, lo, hi)}" aria-label="range slider for ${esc(label)}">`
    + `<span class="max_value" data-testid="max-value">${hi}</span></div></div></div>`;
}
function dropdown(id, key, label, choices, val) {
  const opts = choices.map(([t, v]) => `<option value="${esc(v)}"${v === val ? " selected" : ""}>${esc(t)}</option>`).join("");
  return `<div id="${id}" class="block padded auto-margin gr-dropdown" style="${ST.hidden}"><div class="container"><span class="gr-title" data-testid="block-info">${esc(label)}</span>`
    + `<div class="wrap"><div class="wrap-inner"><div class="secondary-wrap"><select data-k="${key}" aria-label="${esc(label)}">${opts}</select>`
    + `<div class="icon-wrap">${CHEV_SVG}</div></div></div></div></div></div>`;
}
function radio(id, key, label, info, choices, val) {
  const items = choices.map(([t, v]) => `<label class="${v === val ? "selected" : ""}" data-testid="${esc(t)}-radio-label"><input type="radio" name="${key}" value="${esc(v)}"${v === val ? " checked" : ""}><span>${esc(t)}</span></label>`).join("");
  return `<fieldset id="${id}" class="block padded auto-margin gr-radio" data-k="${key}" style="${ST.auto}"><span class="gr-title has-info" data-testid="block-info">${esc(label)}</span>`
    + `<div class="info-text">${esc(info).replace(/\n/g, "<br>")}</div><div class="wrap">${items}</div></fieldset>`;      // brk.kn の改行（句点のあと）
}
const number = (key, label, val) =>
  `<div class="block padded auto-margin gr-number" style="${ST.hidden}"><label class="block container"><span class="gr-title" data-testid="block-info">${esc(label)}</span><input type="number" data-k="${key}" value="${val}" aria-label="${esc(label)}"></label></div>`;
const textbox = (id, ph, grow) =>
  `<div class="block gr-textbox" style="border-style:solid;overflow:hidden;flex-grow:${grow};min-width:min(160px,100%)"><label class="show_textbox_border"><span class="hide sr-only" data-testid="block-info">Textbox</span><div class="input-container"><input id="${id}" class="scroll-hide" type="text" data-testid="textbox" placeholder="${esc(ph)}"></div></label></div>`;

// ---------- 画面 ----------
function topbar() {
  const t = T(), nf = favs().length;
  return `<div id="topbar" class="row unequal-height">${html("brand", L().brand)}${btn("home", t.back)}`
    + `<div id="hsearch" class="row unequal-height">${textbox("q-head", t.sph, 5)}${btn("hbtn", t.sbtn, "secondary", 1)}</div>`
    + `${html("menuhtml", L().m[S.m].menu[S.v].replaceAll("__NFAV__", String(nf)))}</div>`;
}
const navmark = (h) => h.replace(/<i id="navmark" data-depth="\d+" data-stage="\w+"/, `<i id="navmark" data-depth="${S.hist.length}" data-stage="${stage()}"`);

function condForm() {
  const t = T(), F = S.F, A = COMMON.all, core = COMMON.core.length, Ln = L();
  const sl = (i) => slider("s" + i, t.sl[A[i]], 1, 5, F.scores[i], 3);
  let h = (stage() === "cond" ? html("", Ln.m[S.m].numhead[1]) : html("", Ln.m[S.m].chead));
  h += html("", Ln.sec[0], "fsec");
  h += form(`${slider("days", t.days, 1, 10, F.days, 4)}${dropdown("partyd", "party", t.party, t.party_ch, F.party)}${radio("firstr", "first", t.first_lab, Ln.first_info, t.first_ch, F.first)}`);
  h += html("", Ln.sec[1], "fsec");
  h += form(`${number("budget", t.budget, F.budget)}${S.lang === "en" ? dropdown("curc", "cur", Ln.lbl.bgt_cur, [["USD ($)", "USD"], ["EUR (€)", "EUR"]], F.cur) : ""}`);
  h += html("", Ln.sec[2], "fsec");
  h += form(A.slice(0, core).map((_, i) => sl(i)).join(""));
  h += `<div class="block gr-accordion padded auto-margin" style="border-style:solid;overflow:auto;min-width:min(0px,100%)"><button type="button" class="label-wrap${F.acc ? " open" : ""}" aria-expanded="${F.acc}"><span>${esc(t.more)}</span><span class="icon" style="transform:${F.acc ? "rotate(0)" : "rotate(90deg)"}">▼</span></button>`
    + `<div${F.acc ? "" : " hidden"}><div class="column" style="min-width:min(0px,100%)">${form(A.slice(core).map((_, j) => sl(core + j)).join(""))}</div></div></div>`;
  h += btn("go", t.btn, "primary");
  return h;
}

// ④⑤ ページの中身（app.py build_page と同じ振り分け）
async function pageHtml(entry) {
  const [st, pl] = entry, l = S.lang, ctx = { COMMON, Ln: L() };
  if (st === "hotel") {
    const [reg, spot] = pl, id = COMMON.regions[reg].id;
    if (spot === "@area" || spot === "@car" || spot === "@trans") return loadPage(l, `${spot.slice(1)}-${id}`);
    return hotelHtml(S.m, l, reg, spot, ctx);
  }
  const [k, x] = pl;
  if (k === "region") return loadPage(l, `region-${COMMON.regions[x].id}`);
  if (k === "fav") return favHtml(S.m, l, favs(), ctx);
  if (k === "prep" || k === "events") return loadPage(l, `${S.m}-${k}-${monthNow()}`);
  if (k === "hotels" || k === "cars" || k === "trans") return loadPage(l, `${S.m}-${k}`);
  return searchHtml(S.m, l, x, ctx);
}
const regionOf = ([st, pl]) => (st === "hotel" ? pl[0] : st === "list" && pl[0] === "region" ? pl[1] : null);   // app.py region_of

let renderSeq = 0;
async function render() {
  const seq = ++renderSeq, st = stage();
  let page = "";
  if (st === "list" || st === "hotel") {
    try { page = await pageHtml(S.hist[S.hist.length - 1]); }
    catch (e) { console.error(e); toast(FAIL[S.lang]); if (window.tjSpin) window.tjSpin(0); S.hist = S.hist.slice(0, -1); if (seq === renderSeq) return render(); return; }
    if (seq !== renderSeq) return;                         // 読み込み中に別の操作があった
  }
  const Lm = L().m[S.m], t = T();
  // 元アプリ（Gradio）は表示言語によらず <html lang="en">。lang を変えると日本語・繁体字の字形（フォントの選ばれ方）が変わるため、同じ表示になるよう合わせる
  document.documentElement.lang = "en";
  $("#cssS").textContent = COMMON.tokens[`${S.m}|${st === "landing" ? 1 : 0}|${S.lang}`] + COMMON.stage[st];
  $("#cssM").disabled = $("#cssM2").disabled = S.v !== "mobile";
  let h = topbar();
  if (st === "landing") {
    h += html("theme", navmark(Lm.theme.landing)) + bridgeForm();
    h += html("landlang", L().landlang);
    h += `<div id="landing" class="row unequal-height">${btn("pick-tw", LANGS[S.lang].m.taiwan.tx.land)}${btn("pick-jp", LANGS[S.lang].m.japan.tx.land)}</div>`;
    h += html("howtoc", L().howto);
  } else if (st === "cond" || st === "result") {
    const map = Lm.map[S.v === "mobile" ? "mobile" : "pc"];
    h += html("theme", navmark(Lm.theme[st])) + bridgeForm();
    if (st === "cond") h += html("p2t", Lm.p2t);
    h += `<div id="frame" class="column" style="${ST.col(1)}">`;
    if (st === "cond") h += html("kwhead", Lm.numhead[0]) + `<div id="tbar" class="row unequal-height">${textbox("q-page", t.psph, 6)}${btn("pbtn", t.sbtn, "secondary", 1)}</div>`;
    h += `<div id="main" class="row unequal-height"><div id="formcol" class="column" style="${ST.col(4)}">`;
    if (st === "result") h += html("sidemap", map);
    h += `<div id="condbox" class="column" style="${ST.col(1)}">${condForm()}</div>`;
    if (st === "result") h += html("sidecmp", S.res ? S.res.side : "");
    h += `</div><div id="rescol" class="column" style="${ST.col(9)}">`;
    if (st === "cond") h += `<div class="column" style="${ST.col(1)}">${html("maphead", Lm.numhead[2])}${html("", map)}</div>`;
    else h += html("", S.res ? S.res.main : Lm.empty);
    h += `</div></div>`;
    if (st === "cond") h += html("catbox", Lm.catsearch);
    h += `</div>`;
  } else {                                                 // ④⑤ 一覧・ホテル: 背景（エリアの写真 / 国の写真）+ ページ
    const reg = regionOf(S.hist[S.hist.length - 1]);
    h += html("theme", navmark(reg ? COMMON.regions[reg].theme : Lm.theme.cond)) + bridgeForm();
    h += `<div id="pagecol" class="column" style="${ST.col(1)}">${html("", page)}</div>`;
  }
  h += bridgeForm();
  // 背景（スライドショー）が同じなら、元の要素を残してアニメーションを続ける（元アプリも言語切替などで背景を作り直さない）
  const rg = st === "list" || st === "hotel" ? regionOf(S.hist[S.hist.length - 1]) : null;
  const bgKey = st === "landing" ? "landing" : st === "result" ? `result|${S.m}` : rg ? `reg|${rg}` : `bg|${S.m}`, old = document.getElementById("theme");
  const keep = old && old.dataset.key === bgKey ? old : null;
  $("#root").innerHTML = withBase(`<div class="column">${h}</div>`);     // サブフォルダで公開したときは画像の場所を付け替える
  const nw = document.getElementById("theme");
  if (nw) {
    nw.dataset.key = bgKey;
    if (keep) {
      const t2 = nw.querySelectorAll(".ttl"), t1 = keep.querySelectorAll(".ttl");      // トップの国名の下の一文は言語で変わる
      t1.forEach((e, i) => t2[i] && (e.innerHTML = t2[i].innerHTML));
      const nm = nw.querySelector("#navmark"), om = keep.querySelector("#navmark"); if (nm && om) om.replaceWith(nm);
      nw.replaceWith(keep);
    }
  }
  if (st === "list") fixMonth($("#root"), monthNow());    // エリアページの「今月」の印
  if (st === "list") attachTyphoons($("#root"), S.lang);  // 天気欄に活動中の台風の情報（静的サイト版で追加。台風がなければ何も出さない）
  breakTitles();                                           // 見出しは「、」の後でだけ改行する
  if (st === "landing") fitLanding();
  centerBrand();
  phraseBreak();                                          // スマホ: 説明文を文の意味の区切りで改行                                          // PC: 「旅橋 TABIBASHI」を画面左端と「繁」の真ん中に                      // スマホの1ページ目: 余白をなくして写真部分を広げる
  bind();
  if (window.tjSpin) window.tjSpin(0);                     // plan.js が出した「読み込み中」マークを消す（元アプリの SPOFF）
  syncHistory();
}

// ---------- スマホ表示の調整（静的サイト版で追加） ----------
// 「台湾へ、心ゆくままに。」などの見出しが語の途中で折り返さないよう、読点ごとにまとめる
function breakTitles() {
  for (const h of document.querySelectorAll("#hero h1")) {
    if (h.dataset.brk || h.children.length) continue;
    const parts = h.textContent.split(/(?<=[、，,])\s*/).filter(Boolean);
    if (parts.length < 2) continue;
    h.dataset.brk = "1";
    h.innerHTML = parts.map((x) => `<span class="nobr">${x.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c])}</span>`).join("<wbr>");
  }
}
// 「使い方」の高さを測って、残りの高さを TAIWAN / JAPAN の写真に配る（--howh は css/mobile_fix.css が使う）
function fitLanding() {
  const set = () => { const h = document.querySelector("#howtoc .howto"); if (h && h.scrollHeight) document.documentElement.style.setProperty("--howh", (h.scrollHeight + 2) + "px"); };
  set(); requestAnimationFrame(set);
  if (!fitLanding.on) { fitLanding.on = 1; addEventListener("resize", set); document.addEventListener("toggle", set, true); }
}

// PC表示で、ヘッダーの「旅橋 TABIBASHI」を画面左端と「繁」ボタンの真ん中に置く（--bx は css/fix.css が使う）
// 検索欄がヘッダーに出る画面（結果ページなど）では重なるので、元の位置のまま
function centerBrand() {
  const set = () => {
    const tb = $("#topbar"); if (!tb) return;
    const hs = $("#hsearch"), fan = document.querySelector("#menuhtml .hlang a, #menuhtml .hlang button");
    const on = S.v === "pc" && fan && !(hs && hs.offsetWidth);
    tb.classList.toggle("bc", !!on);
    if (!on) return;
    tb.style.setProperty("--bx", (fan.getBoundingClientRect().left - tb.getBoundingClientRect().left) + "px");
    const hm = $("#home"), bl = document.querySelector("#brand .brandlink");      // 幅の狭い画面で「戻る」と重なるなら、元の位置のまま
    if (hm && hm.offsetWidth && bl && bl.getBoundingClientRect().left < hm.getBoundingClientRect().right + 12) tb.classList.remove("bc");
  };
  set();
  if (!centerBrand.on) { centerBrand.on = 1; addEventListener("resize", set); }
}

// スマホ表示で、ページの説明文などが語の途中で改行されないよう、文節（意味のまとまり）の切れ目でだけ改行させる（BudouX）
const PB_SEL = ["p", ".sd", ".evname", ".note", ".info-text", ".trtip > span", ".howto li", "small", ".evlegend li", ".ck > span"].map((x) => "#root " + x).join(",");
let pbObs = null, pbTimer = 0;
// 読点・句点（、。，）までをひとまとまりにする。まとまりが行に収まらないときは次の行へ送るので、読点で区切れるところは読点で改行される
// （まとまりが1行より長いときだけ、その中の文節の切れ目で改行）
const PUNCT = /[、。，！？]/;
function clauses(el) {
  const kids = [...el.childNodes]; let cur = null;
  const flush = () => { cur = null; };
  const add = (n) => { if (!cur) { cur = document.createElement("span"); cur.className = "cl"; el.insertBefore(cur, n); } cur.appendChild(n); };
  for (const n of kids) {
    if (n.nodeType === 3) {
      let t = n.nodeValue, i;
      while ((i = t.search(PUNCT)) >= 0 && i < t.length - 1) {   // 読点の直後で切る
        add(document.createTextNode(t.slice(0, i + 1))); flush(); t = t.slice(i + 1);
      }
      if (t) { const tn = document.createTextNode(t); el.insertBefore(tn, n); add(tn); if (PUNCT.test(t.slice(-1))) flush(); }
      n.remove();
    } else if (n.nodeName === "WBR") { if (cur) cur.appendChild(n); }
    else if (n.nodeName === "BR") flush();
    else { flush(); if (n.nodeType === 1 && !n.matches("input,textarea,select,button,svg")) clauses(n); }
  }
}
// 「エリアから探す」のような短いかぎかっこの中では改行しない（ボタン名などが2行に割れないように）
function keepQuotes(e) {
  const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let depth = 0, inQ = [], n;
  while ((n = w.nextNode())) {
    if (n.nodeType === 3) { for (const ch of n.nodeValue) { if (ch === "「") { depth++; inQ = []; } else if (ch === "」" && depth) { depth--; if (!depth && inQ.len <= 12) inQ.forEach((x) => x.remove()); inQ = []; } else if (depth) inQ.len = (inQ.len || 0) + 1; } }
    else if (n.tagName === "WBR" && depth) inQ.push(n);
  }
}
function phraseBreak() {
  const run = () => {
    const B = window.tjBudoux, mk = B && (S.lang === "ja" ? B.ja : S.lang === "zh" ? B.zh : null);
    if (S.v !== "mobile" || !mk) return;
    const P = mk();
    for (const e of document.querySelectorAll(PB_SEL)) {
      if (e.dataset.pb === S.lang || e.closest("[data-pb]:not(:scope)") || e.querySelector("input,textarea,select,button")) continue;
      try { P.applyToElement(e); keepQuotes(e); clauses(e); e.dataset.pb = S.lang; } catch (err) { /* 改行の調整に失敗しても表示はそのまま */ }
    }
  };
  run();
  if (!pbObs) {                                // あとから描かれる部分（カテゴリの結果・お気に入りなど）にも当てる
    pbObs = new MutationObserver(() => { clearTimeout(pbTimer); pbTimer = setTimeout(run, 60); });
    pbObs.observe(document.getElementById("root"), { childList: true, subtree: true });
  }
}

// ---------- 入力欄の動き ----------
function bind() {
  const root = $("#root");
  root.querySelectorAll(".gr-slider").forEach((box) => {
    const num = $("input[type=number]", box), rng = $("input[type=range]", box), k = box.dataset.k, lo = +rng.min, hi = +rng.max;
    const set = (v, from) => {
      v = Math.min(hi, Math.max(lo, Math.round(+v || lo)));
      if (from !== num) num.value = v; rng.value = v; rng.style.setProperty("--range_progress", pct(v, lo, hi));
      if (k === "days") S.F.days = v; else S.F.scores[+k.slice(1)] = v;
    };
    rng.addEventListener("input", () => set(rng.value, rng));
    num.addEventListener("change", () => set(num.value));
    $(".reset-button", box).addEventListener("click", () => set(box.dataset.def));
  });
  root.querySelectorAll(".gr-dropdown select").forEach((sel) => sel.addEventListener("change", () => {
    const k = sel.dataset.k;
    if (k === "cur") {                                   // 通貨を切り替えたら金額も換算（app.py cur_switch）
      const old = S.F.cur, nw = sel.value; S.F.cur = nw;
      S.F.budget = FX.nice(FX.conv(+S.F.budget || 0, old, nw), nw); const b = $("input[data-k=budget]", root); if (b) b.value = S.F.budget;
    } else S.F[k] = sel.value;
  }));
  root.querySelectorAll(".gr-radio").forEach((fs) => fs.addEventListener("change", (e) => {
    S.F[fs.dataset.k] = e.target.value;
    fs.querySelectorAll("label").forEach((lb) => lb.classList.toggle("selected", $("input", lb).checked));
  }));
  const b = $("input[data-k=budget]", root); if (b) b.addEventListener("input", () => (S.F.budget = b.value === "" ? 0 : +b.value));
  const acc = $(".gr-accordion .label-wrap", root);
  if (acc) acc.addEventListener("click", () => {
    S.F.acc = !S.F.acc; acc.classList.toggle("open", S.F.acc); acc.setAttribute("aria-expanded", S.F.acc);
    $(".icon", acc).style.transform = S.F.acc ? "rotate(0)" : "rotate(90deg)"; acc.nextElementSibling.hidden = !S.F.acc;
  });
  const click = (id, fn) => { const e = document.getElementById(id); if (e) e.addEventListener("click", fn); };
  click("pick-tw", () => pick("taiwan"));
  click("pick-jp", () => pick("japan"));
  click("home", () => nav(S.hist.length > 1 ? S.hist.slice(0, -1) : S.hist));
  click("go", diagnose);
  for (const [box, b2] of [["q-head", "hbtn"], ["q-page", "pbtn"]]) {
    const inp = document.getElementById(box); if (!inp) continue;
    const run = () => search(inp.value);
    click(b2, run); inp.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  }
}

// ---------- 画面遷移 ----------
async function nav(hist, opt = {}) {
  if (opt.m) S.m = opt.m;
  if (opt.v) S.v = opt.v;
  if (opt.lang && opt.lang !== S.lang) { await lang(opt.lang); S.lang = opt.lang; }
  if (opt.reset) S.F = defaultForm(S.m, S.lang);
  if (opt.rebudget) { S.F.budget = T().bval; S.F.cur = "USD"; }             // 言語を変えたら予算欄はその言語の通貨の初期値へ
  S.hist = hist;
  await render();
  if (opt.top !== false) window.scrollTo({ top: 0 });
}
const pick = (m) => nav(COND.slice(), { m, reset: true });
function search(q) {
  q = (q || "").trim();
  if (!q) { if (window.tjSpin) window.tjSpin(0); return; }   // 空欄なら何もしない（ぐるぐるマークも出さない）
  nav(S.hist.concat([["list", ["search", q]]]));
}       // app.py do_search
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const pushPage = (e, opt) => nav(same(S.hist[S.hist.length - 1], e) ? S.hist : S.hist.concat([e]), opt);

// app.py の bridge_in と同じ合図（部品の中の onclick から呼ばれる）
window.tjNav = function (msg) {
  const [a, p1, p2] = String(msg).split("\t");
  if (a === "region" && p1 && COMMON.regions[p1]) return nav(S.hist.concat([["list", ["region", p1]]]), { m: mktOf(p1) });
  if (a === "hotel" && p1 && p2 && COMMON.regions[p1]) return nav(S.hist.concat([["hotel", [p1, p2]]]), { m: mktOf(p1) });
  if (a === "lang" && LANGS_OK.includes(p1)) return nav(S.hist, { lang: p1, rebudget: true, top: false });
  if (a === "menu") {
    if (p1 === "home") return nav(LAND.slice(), { reset: true });
    if (p1 === "cond") return nav(COND.slice());
    if (p1 === "view") return nav(S.hist, { v: S.v === "pc" ? "mobile" : "pc", top: false });
    if (p1 === "other") return nav(COND.slice(), { m: OTHER[S.m], reset: true });
    if (["prep", "events", "hotels", "cars", "trans", "fav"].includes(p1)) return pushPage(["list", [p1, ""]]);
  }
  return nav(S.hist, { top: false });
};
// お気に入り（head.js）が変わったら、メニューの件数とお気に入りページを更新する（app.py set_favs）
let lastFavs = null;
window.tjFavChanged = function () {
  if (!COMMON) return;
  const f = JSON.stringify(favs()); if (f === lastFavs) return; const first = lastFavs === null; lastFavs = f;
  if (first || !COMMON) return;
  const last = S.hist[S.hist.length - 1];
  if (last[0] === "list" && last[1][0] === "fav") return render();
  const mh = document.querySelector("#menuhtml .prose"); if (mh) mh.innerHTML = withBase(L().m[S.m].menu[S.v].replaceAll("__NFAV__", String(favs().length)));
};
// plan.js のカテゴリ一覧の地域ボタン（tjGo）は、元アプリの見えない入力欄 #bridge に書き込む。それを受けて tjNav へ
document.addEventListener("input", (e) => {
  if (e.target && e.target.closest && e.target.closest("#bridge")) { const v = e.target.value.split("\t"); v.pop(); window.tjNav(v.join("\t")); }
}, true);
const LANGS_OK = ["ja", "zh", "en"];

// 診断（③ 結果）。結果画面の本格的な表示は次の手順。ここでは推薦の中身を仮の形で表示する
async function diagnose() {
  const g = $("#go"); if (g) g.disabled = true;
  try {
    DB ||= await loadAll(getJson, "data/");
    const F = S.F, inp = { m: S.m, lang: S.lang, days: F.days, budget: +F.budget || 0, cur: F.cur, party: F.party, first: F.first, scores: F.scores.slice() };
    const R = recommend(DB, inp);
    const [main, side] = await resultHtml(R, inp, { COMMON, Ln: L(), meta: DB.meta, v: S.v, month: monthNow() });
    S.res = { main, side };
    await nav(stage() === "cond" ? S.hist.concat([["result", null]]) : S.hist);
  } finally { if (g) g.disabled = false; }
}
// ---------- ブラウザの「戻る」・再読み込み ----------
let curDepth = 0, pendingBack = 0;
const snap = () => ({ m: S.m, v: S.v, l: S.lang, h: S.hist, F: S.F });
function saveState() { try { sessionStorage.setItem("tj_state", JSON.stringify(snap())); } catch (e) {} }
// 入力欄を変えたら保存（再読み込みしても入力値が残るように）。ページを離れるときにも保存する
document.addEventListener("input", () => { clearTimeout(saveState.tm); saveState.tm = setTimeout(saveState, 150); });
document.addEventListener("change", () => setTimeout(saveState, 0));
window.addEventListener("pagehide", () => { saveState(); try { history.replaceState({ d: S.hist.length, st: snap() }, ""); } catch (e) {} });
function syncHistory() {
  const d = S.hist.length, st = snap();
  saveState();
  if (!curDepth) { history.replaceState({ d, st }, ""); curDepth = d; return; }
  if (d > curDepth) { for (let i = curDepth + 1; i <= d; i++) history.pushState({ d: i, st }, ""); }
  else if (d < curDepth) {
    // 画面内の操作で浅い画面へ移るときは、ブラウザの履歴も戻す。そのときブラウザが昔のスクロール位置に戻さないようにする
    // （戻さないと、メニューの「〇〇旅行を計画する」で検索ページの途中が表示されていた）
    pendingBack++; if ("scrollRestoration" in history) history.scrollRestoration = "manual"; history.go(d - curDepth);
  }
  else history.replaceState({ d, st }, "");
  curDepth = d;
}
window.addEventListener("popstate", async (e) => {
  if (pendingBack > 0) { pendingBack--; history.replaceState({ d: S.hist.length, st: snap() }, ""); if (!pendingBack && "scrollRestoration" in history) history.scrollRestoration = "auto"; return; }
  const s = e.state && e.state.st; if (!s) return;
  curDepth = e.state.d;
  if (s.l !== S.lang) await lang(s.l);
  Object.assign(S, { m: s.m, v: s.v, lang: s.l, hist: s.h.slice(0, e.state.d), F: s.F || S.F });
  if (stage() === "result" && !S.res) return diagnose();
  render();
});
document.addEventListener("click", (e) => {                 // 開いているメニューは外側のクリックで閉じる（元の HEAD スクリプトと同じ）
  document.querySelectorAll("details.menu[open]").forEach((x) => { if (!x.contains(e.target)) x.removeAttribute("open"); });
});

// ---------- 起動（app.py on_load: 共有リンク → 再読み込みの復元 → ブラウザの言語・端末に合わせたトップ） ----------
function parseQ(q) {
  try {
    const m = q.get("m"); if (!["taiwan", "japan"].includes(m)) return null;
    const int = (k) => { const v = q.get(k); if (!/^-?\d+$/.test(v || "")) throw 0; return parseInt(v, 10); };
    const days = Math.min(10, Math.max(1, int("d"))), budget = Math.min(10000000, Math.max(0, int("b"))), party = q.get("p");
    if (!["solo", "couple", "friends", "family"].includes(party)) return null;
    const sc = (q.get("s") || "").split(",").map((x) => { if (!/^-?\d+$/.test(x)) throw 0; return Math.min(5, Math.max(1, parseInt(x, 10))); });
    if (sc.length !== COMMON.all.length) return null;
    return { m, days, budget, party, first: !!int("f"), sc, cur: ["USD", "EUR"].includes(q.get("c")) ? q.get("c") : "USD" };
  } catch (e) { return null; }
}
async function start() {
  COMMON = await getJson("data/ui.json");
  FX = makeFx((await getJson("data/meta.json")).FX);
  const first = (navigator.languages && navigator.languages[0]) || navigator.language || "";
  const dl = /^ja/i.test(first) ? "ja" : /^zh/i.test(first) ? "zh" : "en";
  const dv = /Mobi|iPhone|iPod/.test(navigator.userAgent) ? "mobile" : "pc";
  const q = new URLSearchParams(location.search), P = parseQ(q);
  let saved = null;
  try { const nt = (performance.getEntriesByType("navigation")[0] || {}).type; if (nt === "reload" || nt === "back_forward") saved = JSON.parse(sessionStorage.getItem("tj_state") || "null") || (history.state && history.state.st); } catch (e) {}
  if (saved && ["taiwan", "japan"].includes(saved.m) && LANGS_OK.includes(saved.l)) {
    await lang(saved.l); Object.assign(S, { m: saved.m, v: saved.v === "mobile" ? "mobile" : "pc", lang: saved.l, hist: saved.h, F: saved.F || defaultForm(saved.m, saved.l) });
    curDepth = 0;
    if (stage() === "result") return diagnose();             // 結果は保存してある条件で計算し直す（app.py on_load の復元と同じ）
    return render();
  }
  if (P) {
    const l = LANGS_OK.includes(q.get("l")) ? q.get("l") : dl;
    await lang(l); Object.assign(S, { m: P.m, lang: l, v: ["pc", "mobile"].includes(q.get("v")) ? q.get("v") : dv });
    S.F = Object.assign(defaultForm(P.m, l, P.cur), { days: P.days, budget: P.budget, party: P.party, first: P.first ? "first" : "repeat", scores: P.sc, cur: P.cur });
    S.hist = COND.slice(); render(); return diagnose();
  }
  await lang(dl); Object.assign(S, { lang: dl, v: dv, F: defaultForm(S.m, dl) });
  render();
}
start().catch((e) => { console.error(e); document.getElementById("root").textContent = "読み込みに失敗しました: " + e.message; });
