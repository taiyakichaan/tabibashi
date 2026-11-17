"""静的サイトの全ページを実際にブラウザで開いて点検する（Python版との比較ではなく、壊れていないかの点検）。
  ・読み込みに失敗した通信（404 など。天気の外部 API と元アプリのサーバー経由の予備経路は除く）
  ・ページ内のすべての画像（<img> と背景画像）を実際に取得して、画像として読めるか
  ・JS のエラー
  ・画面に出てはいけない文字（undefined / NaN / [object / 差し込み用の目印 / 未置換の {n} など）
  ・スマホ幅で横にはみ出していないか（横スクロールが出る）
使い方: cd site && python -m http.server 8765   （別の端末で）
        python tests/crawl.py [http://localhost:8765/] [--quick]"""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright

U = next((x for x in sys.argv[1:] if x.startswith("http")), "http://localhost:8765/")
QUICK = "--quick" in sys.argv
SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")
COMMON = json.load(open(os.path.join(SITE, "data", "ui.json"), encoding="utf-8"))
REGS = sorted(COMMON["regions"])
IGNORE = re.compile(r"open-meteo\.com|jma\.go\.jp/bosai/typhoon|/gradio_api/|fonts\.(googleapis|gstatic)\.com")
BADTXT = re.compile(r"undefined|NaN|\[object|__NFAV__|[\x01-\x06]|\{(?:n|p|m|s|t|reg|spot|term|q)\}")
problems = []; checked_img = {}
def prob(where, what): problems.append((where, what)); print("NG", where, what[:300])

def check_page(pg, where, mobile=False):
    pg.wait_for_timeout(250)
    txt = pg.evaluate("document.querySelector('#root').innerText")
    m = BADTXT.search(txt)
    if m: prob(where, f"表示崩れの文字 {m.group(0)!r}: …{txt[max(0, m.start() - 40):m.end() + 40]!r}")
    urls = pg.evaluate("""() => { const s = new Set();
      document.querySelectorAll('#root *').forEach(e => { const b = getComputedStyle(e).backgroundImage;
        (b || '').replace(/url\\(["']?([^"')]+)["']?\\)/g, (m, u) => { if (!u.startsWith('data:')) s.add(new URL(u, location.href).href); }); });
      document.querySelectorAll('#root img').forEach(i => { if (i.getAttribute('src') && !i.src.startsWith('data:')) s.add(i.src); });
      document.querySelectorAll('#root [data-bg]').forEach(e => s.add(new URL(e.dataset.bg, location.href).href));
      return [...s]; }""")
    new = [u for u in urls if u not in checked_img and not IGNORE.search(u)]
    if new:
        res = pg.evaluate("""async (urls) => Promise.all(urls.map(u => new Promise(r => { const i = new Image(); i.onload = () => r([u, i.naturalWidth > 0]); i.onerror = () => r([u, false]); i.src = u; })))""", new)
        for u, ok in res:
            checked_img[u] = ok
            if not ok: prob(where, f"画像を読めない {u}")
    if mobile:
        ov = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        if ov[0] > ov[1] + 1: prob(where, f"横にはみ出し scrollWidth={ov[0]} > 画面幅{ov[1]}")

def run(b, lang, mobile):
    ctx = b.new_context(viewport=dict(width=390, height=844) if mobile else dict(width=1440, height=900), is_mobile=mobile, has_touch=mobile,
                        locale={"ja": "ja-JP", "zh": "zh-TW", "en": "en-US"}[lang],
                        user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1" if mobile else None))
    pg = ctx.new_page(); tag = f"{lang}/{'sp' if mobile else 'pc'}"
    pg.on("pageerror", lambda e: prob(tag, f"JSエラー {e}"))
    pg.on("console", lambda m: prob(tag, f"console.error {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("response", lambda r: prob(tag, f"HTTP {r.status} {r.url}") if r.status >= 400 and not IGNORE.search(r.url) else None)
    pg.on("requestfailed", lambda r: prob(tag, f"通信失敗 {r.url} {r.failure}") if not IGNORE.search(r.url) else None)
    pg.goto(U); pg.wait_for_selector("#landing", state="visible", timeout=30000); pg.wait_for_timeout(800)
    check_page(pg, f"{tag} トップ", mobile)
    def go(msg, sel, where):
        pg.evaluate("(m) => window.tjNav(m)", msg)
        try: pg.wait_for_selector(sel, timeout=15000)
        except Exception: prob(where, f"表示されない（{sel}）"); return
        check_page(pg, where, mobile)
    for m, pick in (("taiwan", "#pick-tw"), ("japan", "#pick-jp")):
        pg.evaluate("tjNav('menu\\thome')"); pg.wait_for_selector("#landing", state="visible"); pg.click(pick); pg.wait_for_selector("#frame")
        check_page(pg, f"{tag} 条件 {m}", mobile)
        pg.click("#go"); pg.wait_for_selector("#rescol .regions .rw", timeout=30000); check_page(pg, f"{tag} 結果 {m}", mobile)
        for k, sel in (("hotels", ".pg, .lux"), ("cars", ".pg, .lux"), ("trans", ".pg, .lux"), ("events", ".pg, .lux"), ("prep", ".pg, .lux")):
            go(f"menu\t{k}", "#pagecol " + sel.split(",")[0] + ", #pagecol" + sel.split(",")[1], f"{tag} {m} {k}")
    regs = REGS[:6] if QUICK else REGS
    for reg in regs:
        go(f"region\t{reg}", "#pagecol .pgcover", f"{tag} エリア {reg}")
        cov = pg.evaluate("getComputedStyle(document.querySelector('#pagecol .pgcover')).backgroundImage")
        if "url(" not in cov: prob(f"{tag} エリア {reg}", f"見出し写真が指定されていない: {cov[:80]}")
        if not mobile:
            for k in ("area", "car", "trans"): go(f"hotel\t{reg}\t@{k}", "#pagecol .pg, #pagecol .lux", f"{tag} {k} {reg}")
    # お気に入り・検索・スポットのホテル
    pg.evaluate("""() => { localStorage.setItem('tj_favs', JSON.stringify([['北海道','小樽運河'],['台南市','安平老街'],['京都府','清水寺']])); }""")
    pg.reload(); pg.wait_for_selector("#root .column"); pg.wait_for_timeout(600)
    go("menu\tfav", "#pagecol .favpg .spot", f"{tag} お気に入り")
    for q in ("温泉", "Taipei", "老街", "xyz"):
        pg.evaluate("tjNav('menu\\tcond')"); pg.wait_for_selector("#tbar input")
        pg.fill("#tbar input", q); pg.press("#tbar input", "Enter")
        try: pg.wait_for_selector("#pagecol .srch", timeout=15000); check_page(pg, f"{tag} 検索 {q}", mobile)
        except Exception: prob(f"{tag} 検索 {q}", "表示されない")
    go("hotel\t京都府\t清水寺", "#pagecol .hotelx", f"{tag} スポットのホテル")
    ctx.close()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"))
    for lang in ("ja", "zh", "en"):
        for mobile in (False, True):
            t0 = time.time(); n0 = len(problems); run(b, lang, mobile)
            print(f"-- {lang} {'スマホ' if mobile else 'PC'}: 問題 {len(problems) - n0} 件（{time.time() - t0:.0f}秒）")
    b.close()
# 書き出したページは全部取得できるか（12か月分のイベント・準備など、画面からは今月しか開かないものも）
import urllib.request
names = [f"{l}/{f}" for l in ("ja", "zh", "en") for f in os.listdir(os.path.join(SITE, "data", "pages", l))]
bad = []
for n in names:
    try: urllib.request.urlopen(U + "data/pages/" + n).read(10)
    except Exception as e: bad.append((n, str(e)))
print(f"書き出しページの取得: {len(names)} 件 失敗 {len(bad)} {bad[:3]}")
print(f"画像の確認: {len(checked_img)} 枚 読めない {sum(1 for v in checked_img.values() if not v)}")
print("OK: 問題なし" if not problems and not bad else f"NG: {len(problems) + len(bad)} 件")
sys.exit(1 if problems or bad else 0)
