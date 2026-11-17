"""入力によって変わるページ（結果・お気に入り・検索・スポットのホテル）の HTML が、Python版と文字単位で同じかを確かめる。
静的版の js/pages.js をブラウザ（Chrome）で動かし、元の app.py の出力と比べる。エリアページの「今月」の付け直しも確かめる。
使い方: cd site && python -m http.server 8765   （別の端末で）
        python tests/test_pages.py <元アプリのフォルダ（パッチ適用済み）> [http://localhost:8765/] [ケース数=60]"""
import datetime as _dt, json, os, random, sys
from urllib.parse import quote
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from load_app import load, asset_url, ascii_name
from playwright.sync_api import sync_playwright

APP = os.path.abspath(sys.argv[1]); U = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8765/"; N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
a = load(APP)
a.asset = asset_url(a)                                                   # 画像 URL: /gradio_api/file=<絶対パス> → /images/...（英字のファイル名）
for name in dir(a):
    fn = getattr(a, name)
    if callable(fn) and hasattr(fn, "cache_clear"): fn.cache_clear()
import fx
rnd = random.Random(5); LANGS = ["ja", "zh", "en"]; NG = []
def check(kind, case, py, js):
    if py == js: return True
    i = next((k for k in range(min(len(py), len(js))) if py[k] != js[k]), min(len(py), len(js)))
    NG.append(kind); print(f"NG {kind} {json.dumps(case, ensure_ascii=False)[:160]}\n   python: …{py[max(0, i - 80):i + 80]!r}\n   js    : …{js[max(0, i - 80):i + 80]!r}")
    return False

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome")); pg = b.new_page()
    pg.goto(U + "data/ui.json")
    pg.evaluate("""async () => {
      const P = await import('/js/pages.js'), Rc = await import('/js/recommend.js');
      const j = (u) => fetch(u).then(r => r.json());
      window.T = { P, Rc, COMMON: await j('/data/ui.json'), L: {}, DB: await Rc.loadAll(j, '/data/') };
      for (const l of ['ja','zh','en']) window.T.L[l] = await j('/data/ui_' + l + '.json');
    }""")
    js = lambda code, arg: pg.evaluate(code, arg)
    month = _dt.date.today().month

    # ---- ③ 結果 ----
    ok = 0
    for k in range(N):
        m = rnd.choice(["taiwan", "japan"]); lang = rnd.choice(LANGS); cur = rnd.choice(["USD", "EUR"]) if lang == "en" else "USD"
        cu = fx.cur_of(lang, cur); budget = int(fx.default_budget(m, cu) * rnd.choice([0.3, 1, 2, 5]))
        inp = dict(m=m, lang=lang, days=rnd.randint(1, 10), budget=budget, cur=cur, party=rnd.choice(["solo", "couple", "friends", "family"]), first=rnd.choice(["first", "repeat"]), scores=[rnd.randint(1, 5) for _ in a.ALL])
        v = rnd.choice(["pc", "mobile"])
        pm, ps = a.recommend(m, lang, inp["days"], inp["budget"], inp["party"], inp["first"], *inp["scores"], v=v, cur=cur)
        jm, jsd = js("""async ([inp, v, month]) => { const T = window.T, R = T.Rc.recommend(T.DB, inp);
            return await T.P.resultHtml(R, inp, { COMMON: T.COMMON, Ln: T.L[inp.lang], meta: T.DB.meta, v, month }); }""", [inp, v, month])
        ok += check("結果(本文)", inp, pm, jm) & check("結果(比較・ブロック)", inp, ps, jsd)
    print(f"結果: {ok}/{N} 一致")

    # ---- お気に入り ----
    allsp = {m: list(a.D[m]["spots"].drop_duplicates(["region", "spot"])[["region", "spot"]].itertuples(index=False)) for m in ("taiwan", "japan")}
    ok = 0; n = 0
    for k in range(20):
        m = rnd.choice(["taiwan", "japan"]); lang = rnd.choice(LANGS)
        favs = [list(rnd.choice(allsp[rnd.choice(["taiwan", "japan"])])) for _ in range(rnd.choice([0, 1, 3, 8]))]
        if favs and rnd.random() < .3: favs.append(["存在しない", "x"]); favs.append(list(favs[0]))      # 検証で落ちるもの・重複
        clean = [x for i, x in enumerate(favs) if x[0] in a.ALLREG and x not in favs[:i]]
        py = a.build_page(m, lang, ("list", ("fav", "")), clean)
        jj = js("""async ([m, lang, favs]) => { const T = window.T; return await T.P.favHtml(m, lang, T.P.cleanFavs(favs, T.COMMON), { COMMON: T.COMMON, Ln: T.L[lang] }); }""", [m, lang, favs])
        n += 1; ok += check("お気に入り", dict(m=m, lang=lang, favs=favs), py, jj)
    print(f"お気に入り: {ok}/{n} 一致")

    # ---- 検索 ----
    qs = ["台北", "京都", "kyoto", "ＫＹＯＴＯ", "Taipei", "温泉", "溫泉", "Hot springs", "神社", "夜市", "老街", "城", "museum", "美術館", "台灣", "日本", "japan", "臺南", "沖縄", "a", "東京タワー", "存在しないスポット名xyz", "  花蓮  ", "島", "Castle", "ビーチ"]
    ok = 0; n = 0
    for q in qs:
        for lang in LANGS:
            m = rnd.choice(["taiwan", "japan"]); q2 = q.strip()
            py = a.build_page(m, lang, ("list", ("search", q2)))
            jj = js("""async ([m, lang, q]) => { const T = window.T; return await T.P.searchHtml(m, lang, q, { COMMON: T.COMMON, Ln: T.L[lang] }); }""", [m, lang, q2])
            n += 1; ok += check("検索", dict(m=m, lang=lang, q=q2), py, jj)
    print(f"検索: {ok}/{n} 一致")

    # ---- スポットのホテル ----
    ok = 0; n = 0
    for k in range(60):
        m = rnd.choice(["taiwan", "japan"]); lang = rnd.choice(LANGS); reg, spot = rnd.choice(allsp[m])
        py = a.build_page(m, lang, ("hotel", (reg, spot)))
        jj = js("""async ([m, lang, reg, spot]) => { const T = window.T; return await T.P.hotelHtml(m, lang, reg, spot, { COMMON: T.COMMON, Ln: T.L[lang] }); }""", [m, lang, reg, spot])
        n += 1; ok += check("ホテル", dict(m=m, lang=lang, reg=reg, spot=spot), py, jj)
    print(f"スポットのホテル: {ok}/{n} 一致")

    # ---- エリアページの「今月」 ----
    class FD(_dt.date):
        mo = 1
        @classmethod
        def today(cls): return _dt.date(2026, cls.mo, 10)
    class FDT: date = FD; datetime = _dt.datetime
    real = a.datetime; ok = 0; n = 0
    regs = sorted(a.ALLREG)
    try:
        a.datetime = FDT
        for mo in (1, 4, 8, 12):
            FD.mo = mo; a._region_page.cache_clear() if hasattr(a._region_page, "cache_clear") else None
            for reg in rnd.sample(regs, 4):
                lang = rnd.choice(LANGS); m = a.mkt_of(reg)
                py = a.build_page(m, lang, ("list", ("region", reg))).replace("/gradio_api/", "/gradio_api/")
                same = js("""async ([py, lang, id, mo]) => { const T = window.T, h = await T.P.loadPage(lang, 'region-' + id);
                    const d1 = document.createElement('div'), d2 = document.createElement('div'); d1.innerHTML = h; d2.innerHTML = py; T.P.fixMonth(d1, mo);
                    return d1.innerHTML === d2.innerHTML; }""", [py, lang, a_id if (a_id := json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "data", "ui.json"), encoding="utf-8"))["regions"][reg]["id"]) is not None else 0, mo])
                n += 1; ok += same
                if not same: NG.append("今月"); print("NG 今月", reg, lang, mo)
    finally:
        a.datetime = real
    print(f"エリアページの今月: {ok}/{n} 一致")
    b.close()
print("OK: すべて Python版と一致" if not NG else f"NG: {len(NG)} 件")
sys.exit(1 if NG else 0)
