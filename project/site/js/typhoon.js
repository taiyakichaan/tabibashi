// エリアページの天気欄（「現在の天気と2週間予報」）に、活動中の台風の情報を添える。静的サイト版で追加した機能（元アプリにはない）。
// データ: 気象庁の台風情報 JSON（www.jma.go.jp/bosai/typhoon/data/。CORS 開放・キー不要）を閲覧者のブラウザから直接取得する。
//   targetTc.json                 活動中の台風・熱帯低気圧の一覧
//   <TC番号>/specifications.json  実況（advancedHours=0）と予報（24〜120時間後）の位置・中心気圧・最大風速・進路・速さ
// 台風がないときは見出しの横に「台風情報なし」、取得できないときは「台風情報を取得できません」（どちらも気象庁のページへのリンク）。
const API = "https://www.jma.go.jp/bosai/typhoon/data/";
const KEY = "tj_typhoon1", FRESH = 10 * 60 * 1000;
const NEAR_KM = 500;                       // 予報上の最接近がこの距離以内なら「接近のおそれ」

const T = {
  ja: { none: "台風情報なし", noneT: "現在、発表中の台風情報はありません（気象庁）", fail: "台風情報を取得できません", failT: "気象庁の台風情報を読み込めませんでした。押すと気象庁のページを開きます",
        chip: (n) => `台風 ${n}個 活動中`, near: "接近のおそれ", ty: (no) => `台風第${no}号`, td: "熱帯低気圧", pres: "中心気圧", wind: "最大風速", gust: "最大瞬間",
        from: (dir, km) => `このエリアから${dir}へ約${km}km`, move: "進路", closest: (km, t) => `予報上の最接近 約${km}km（${t}ごろ）`,
        src: (t) => `出典：気象庁「台風情報」（${t} 発表）`, more: "気象庁の台風情報", link: "https://www.jma.go.jp/bosai/map.html#contents=typhoon" },
  zh: { none: "目前無颱風", noneT: "目前沒有發布中的颱風資訊（日本氣象廳）", fail: "無法取得颱風資訊", failT: "無法載入日本氣象廳的颱風資訊，點選可開啟氣象廳網頁",
        chip: (n) => `${n} 個颱風活動中`, near: "可能接近", ty: (no) => `第${no}號颱風`, td: "熱帶性低氣壓", pres: "中心氣壓", wind: "最大風速", gust: "最大陣風",
        from: (dir, km) => `位於此地區${dir}方約 ${km} 公里`, move: "移動", closest: (km, t) => `預報最接近約 ${km} 公里（${t}前後）`,
        src: (t) => `資料來源：日本氣象廳 颱風資訊（${t} 發布）`, more: "日本氣象廳 颱風資訊", link: "https://www.jma.go.jp/bosai/map.html#lang=en&contents=typhoon" },
  en: { none: "No active typhoons", noneT: "No typhoon information is currently being issued (Japan Meteorological Agency)", fail: "Typhoon info unavailable", failT: "Could not load JMA typhoon information. Click to open the JMA page",
        chip: (n) => (n > 1 ? `${n} active tropical cyclones` : "Active tropical cyclone"), near: "May approach", ty: (no) => `Typhoon No. ${no}`, td: "Tropical depression", pres: "Pressure", wind: "Max wind", gust: "gusts",
        from: (dir, km) => `about ${km} km ${dir} of this area`, move: "Moving", closest: (km, t) => `Closest forecast approach about ${km} km (around ${t})`,
        src: (t) => `Source: Japan Meteorological Agency, typhoon information (issued ${t})`, more: "JMA typhoon information", link: "https://www.jma.go.jp/bosai/map.html#lang=en&contents=typhoon" },
};
// 気象庁の日本語の値を各言語へ
const DIRS = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"];
const DIR = {
  ja: DIRS,
  zh: ["北", "北北東", "東北", "東北東", "東", "東南東", "東南", "南南東", "南", "南南西", "西南", "西南西", "西", "西北西", "西北", "北北西"],
  en: ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"],
};
const CAT = { zh: { TY: "颱風", STS: "強烈熱帶風暴", TS: "熱帶風暴", TD: "熱帶性低氣壓" }, en: { TY: "Typhoon", STS: "Severe tropical storm", TS: "Tropical storm", TD: "Tropical depression" } };
const WORD = {
  zh: { "強い": "強", "非常に強い": "非常強", "猛烈な": "猛烈", "大型": "大型", "超大型": "超大型", "不定": "方向不定", "ほとんど停滞": "幾乎停滯", "停滞": "停滯", "ゆっくり": "緩慢" },
  en: { "強い": "strong", "非常に強い": "very strong", "猛烈な": "violent", "大型": "large", "超大型": "very large", "不定": "erratic", "ほとんど停滞": "almost stationary", "停滞": "stationary", "ゆっくり": "slowly" },
};
const tr = (lang, s) => (lang === "ja" ? s : (WORD[lang] && WORD[lang][s]) || s);
const course = (lang, s) => { const i = DIRS.indexOf(s); return i >= 0 ? DIR[lang][i] : tr(lang, s); };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function km(a, b) {                       // 大圏距離
  const R = 6371, r = Math.PI / 180, dl = (b[0] - a[0]) * r, dn = (b[1] - a[1]) * r;
  const h = Math.sin(dl / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dn / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
function bearing(a, b) {                  // a から見た b の方角（16方位の番号）
  const r = Math.PI / 180, y = Math.sin((b[1] - a[1]) * r) * Math.cos(b[0] * r);
  const x = Math.cos(a[0] * r) * Math.sin(b[0] * r) - Math.sin(a[0] * r) * Math.cos(b[0] * r) * Math.cos((b[1] - a[1]) * r);
  return Math.round(((Math.atan2(y, x) / r + 360) % 360) / 22.5) % 16;
}
const round10 = (x) => Math.max(10, Math.round(x / 10) * 10);
// 時刻はそのエリアの現地時間で「11/19 21:00 日本時間」の形に（台湾のエリアは台湾時間）
const TZN = { ja: { "Asia/Tokyo": "日本時間", "Asia/Taipei": "台湾時間" }, zh: { "Asia/Tokyo": "日本時間", "Asia/Taipei": "台灣時間" }, en: { "Asia/Tokyo": "JST", "Asia/Taipei": "Taiwan time" } };
const tzOf = (here) => (here[1] < 122.2 ? "Asia/Taipei" : "Asia/Tokyo");
function when(iso, lang, tz) {
  const d = new Date(iso); if (isNaN(d)) return "";
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d).map((x) => [x.type, x.value]));
  const lab = TZN[lang][tz];
  return `${p.month}/${p.day} ${p.hour}:${p.minute} ${lab}`;
}

// ---------- 取得（10分間は保存したものを使う。同時の取得は1回にまとめる） ----------
let inflight = null;
async function getJson(url, ms = 10000) {
  const ctl = "AbortController" in window ? new AbortController() : null, t = setTimeout(() => ctl && ctl.abort(), ms);
  try { const r = await fetch(url, ctl ? { signal: ctl.signal, cache: "no-cache" } : {}); if (!r.ok) throw new Error(String(r.status)); return await r.json(); }
  finally { clearTimeout(t); }
}
export function loadTyphoons() {
  try { const c = JSON.parse(localStorage.getItem(KEY) || "null"); if (c && Date.now() - c.t < FRESH && Array.isArray(c.list)) return Promise.resolve(c.list); } catch (e) {}
  return (inflight ||= (async () => {
    const list = await getJson(API + "targetTc.json");
    const out = [];
    for (const tc of (Array.isArray(list) ? list : []).slice(0, 6)) {
      if (!tc || !/^TC\d+$/.test(tc.tropicalCyclone || "")) continue;
      try {
        const spec = await getJson(`${API}${tc.tropicalCyclone}/specifications.json`);
        const title = spec.find((p) => p.part === "title") || {};
        const now = spec.find((p) => p.advancedHours === 0 && p.position && p.position.deg);
        if (!now) continue;
        out.push({
          id: tc.tropicalCyclone, number: (title.typhoonNumber || tc.typhoonNumber || "").slice(2).replace(/^0/, ""),
          name: title.name || {}, cat: (now.category && now.category.en) || tc.category || "", catJp: (now.category && now.category.jp) || "",
          issue: (title.issue && (title.issue.JST || title.issue.UTC)) || tc.issue || "",
          pos: now.position.deg, pressure: now.pressure, wind: now.maximumWind || {}, scale: now.scale, intensity: now.intensity,
          course: now.course, speed: now.speed || {},
          fc: spec.filter((p) => typeof p.advancedHours === "number" && p.advancedHours > 0 && p.position && p.position.deg)
            .map((p) => ({ h: p.advancedHours, pos: p.position.deg, t: p.validtime && (p.validtime.JST || p.validtime.UTC) })),
        });
      } catch (e) { /* 1つ取れなくても他は出す */ }
    }
    try { localStorage.setItem(KEY, JSON.stringify({ t: Date.now(), list: out })); } catch (e) {}
    return out;
  })().finally(() => { inflight = null; }));
}

// ---------- 表示 ----------
const ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M12 12m-2.2 0a2.2 2.2 0 1 0 4.4 0a2.2 2.2 0 1 0 -4.4 0"/><path d="M14.5 4.5C10 3 5.5 6 5 10.5"/><path d="M9.5 19.5C14 21 18.5 18 19 13.5"/><path d="M19.5 9.5C18 6.5 15 5 12 5"/><path d="M4.5 14.5C6 17.5 9 19 12 19"/></svg>';
function card(tcy, here, lang) {
  const tz = tzOf(here), L = T[lang], dist = km(here, tcy.pos), dir = DIR[lang][bearing(here, tcy.pos)];
  let close = null;
  for (const f of tcy.fc) { const d = km(here, f.pos); if (!close || d < close.d) close = { d, t: f.t }; }
  if (close && dist < close.d) close = null;                                   // 遠ざかっている（今が一番近い）
  const near = Math.min(dist, close ? close.d : Infinity) <= NEAR_KM;
  const nm = tcy.name.en ? (lang === "ja" && tcy.name.jp ? `${tcy.name.en}（${tcy.name.jp}）` : tcy.name.en) : "";
  const td = tcy.cat === "TD" || !tcy.number;
  // 見出し: 日本語「台風第25号 USAGI（ウサギ）」/ 繁體「第25號颱風 USAGI」/ 英語「Typhoon USAGI (No. 25)」（英語は階級の名前で呼ぶ）
  const head = td ? (lang === "ja" ? tcy.catJp || L.td : CAT[lang].TD)
    : lang === "en" ? `${CAT.en[tcy.cat] || "Typhoon"}${nm ? ` ${nm}` : ""} (No. ${tcy.number})` : `${L.ty(tcy.number)}${nm ? ` ${nm}` : ""}`;
  const sep = lang === "en" ? ", " : "・";
  const grade = [tcy.scale, tcy.intensity].filter((x) => x && x !== "-").map((x) => tr(lang, x));
  const sub = (lang === "zh" && !td ? [CAT.zh[tcy.cat] || ""] : []).concat(grade).filter(Boolean).join(sep);
  const sus = tcy.wind.sustained && tcy.wind.sustained["m/s"], gust = tcy.wind.gust && tcy.wind.gust["m/s"];
  const spd = tcy.speed["km/h"] ? `${tcy.speed["km/h"]} km/h` : (tcy.speed.note && tcy.speed.note.jp ? tr(lang, tcy.speed.note.jp) : "");
  const facts = [
    tcy.pressure && tcy.pressure !== "-" ? `${L.pres} <b>${esc(tcy.pressure)}</b> hPa` : "",
    sus && sus !== "-" ? `${L.wind} <b>${esc(sus)}</b> m/s${gust && gust !== "-" ? `（${L.gust} ${esc(gust)} m/s）` : ""}` : "",
    tcy.course ? `${L.move} ${esc(course(lang, tcy.course))}${spd ? ` ${esc(spd)}` : ""}` : "",
  ].filter(Boolean).map((x) => `<li>${x}</li>`).join("");
  return `<div class="tyc${near ? " near" : ""}"><div class="tyh"><b>${esc(head)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}${near ? `<em>${L.near}</em>` : ""}</div>`
    + `<p class="typ">${esc(L.from(dir, round10(dist)))}</p><ul class="tyf">${facts}</ul>`
    + (close && close.d <= NEAR_KM * 2 ? `<p class="tyn">${esc(L.closest(round10(close.d), when(close.t, lang, tz)))}</p>` : "") + `</div>`;
}
function header(wx) {                      // 見出し（h3）と札を横に並べる枠
  const h3 = wx.querySelector(":scope > h3, :scope > .wxhd > h3"); if (!h3) return null;
  let hd = wx.querySelector(":scope > .wxhd");
  if (!hd) { hd = document.createElement("div"); hd.className = "wxhd"; h3.before(hd); hd.appendChild(h3); }
  return hd;
}
// list: 活動中の台風（空なら「台風情報なし」）、null なら取得失敗（「取得できません」）
export function render(wx, list, lang) {
  wx.querySelectorAll(".tychip,.typh").forEach((e) => e.remove());
  const L = T[lang] || T.en, hd = header(wx); if (!hd) return;
  if (!list || !list.length) {
    const k = list ? "none" : "fail";
    hd.insertAdjacentHTML("beforeend", `<a class="tychip ${k}" href="${L.link}" target="_blank" rel="noopener" title="${esc(L[k + "T"])}">${ICON}<span>${esc(L[k])}</span></a>`);
    return;
  }
  const here = [+wx.dataset.lat, +wx.dataset.lon];
  const sorted = list.slice().sort((a, b) => km(here, a.pos) - km(here, b.pos));
  const html = sorted.map((t) => card(t, here, lang)).join("");
  const anyNear = html.includes('class="tyc near"');
  hd.insertAdjacentHTML("beforeend", `<a class="tychip${anyNear ? " near" : ""}" href="#typh-${esc(wx.dataset.lat)}" onclick="var e=this.closest('.wx').querySelector('.typh');if(e)e.scrollIntoView({behavior:'smooth',block:'nearest'});return false">${ICON}<span>${esc(anyNear ? L.near : L.chip(list.length))}</span></a>`);
  const issue = sorted.map((t) => t.issue).filter(Boolean).sort().pop(), tz = tzOf(here);
  hd.insertAdjacentHTML("afterend", `<div class="typh" id="typh-${esc(wx.dataset.lat)}" role="region" aria-label="${esc(L.chip(list.length))}">${html}`
    + `<p class="tycr">${esc(L.src(issue ? when(issue, lang, tz) : ""))} · <a href="${L.link}" target="_blank" rel="noopener">${esc(L.more)}</a></p></div>`);
}
// 画面の中の天気欄すべてに付ける（取得中に画面が描き直されたら、そのとき表示中の欄に付ける）
export function attachTyphoons(root, lang) {
  if (!root.querySelector(".wx[data-lat]")) return;
  const all = (list) => document.querySelectorAll(".wx[data-lat]").forEach((wx) => render(wx, list, wx.dataset.lang || lang));
  loadTyphoons().then(all, () => all(null));
}
