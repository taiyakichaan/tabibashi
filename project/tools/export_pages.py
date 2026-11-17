"""元アプリ(Python版)の各ページを、静的サイト用に書き出す。
使い方: python tools/export_pages.py <元アプリのフォルダ（パッチ適用済み）> <出力先 site フォルダ>

入力によらず中身が決まるページは、app.py の build_page() の出力をそのまま HTML ファイルにする（文言・改行・リンクも同じ）。
  data/pages/<言語>/region-<id>.html      エリアのスポット一覧（今月の印はブラウザ側で付け直す）
  data/pages/<言語>/area-<id>.html        エリアのホテル予約サイト一覧
  data/pages/<言語>/car-<id>.html         エリアのレンタカー
  data/pages/<言語>/trans-<id>.html       エリア内の交通手段
  data/pages/<言語>/<国>-hotels|cars|trans.html          国全体のホテル・レンタカー・交通
  data/pages/<言語>/<国>-events-<月>.html, <国>-prep-<月>.html  イベントカレンダー・旅の準備（今月によって表示が変わるので12か月分）
入力によって変わるページ（結果・お気に入り・検索・スポットごとのホテル）は js/pages.js が組み立てる。そのための部品も書き出す。
  data/hotel_terms_<国>.json   スポット → ホテル検索語（市区町村名）と、その URL 符号化（UTF-8 / EUC-JP）
  data/search.json             サイト内検索の索引（正規化済みの地域名・スポット名・分類名）
  data/ui.json / ui_<言語>.json に結果画面・お気に入り・検索で使う文言とひな形を追記する
"""
import datetime as _dt, json, os, re, sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from load_app import load, asset_url, ascii_name

P_REG, P_SPOT, P_TERM, P_UTF, P_EUC, P_REGEN = "\x01", "\x02", "\x03", "\x04", "\x05", "\x06"     # ホテルのひな形の差し込み位置


def main(app_dir, site_dir):
    app_dir, site_dir = os.path.abspath(app_dir), os.path.abspath(site_dir)
    a = load(app_dir)
    import guide, fx
    a.asset = asset_url(a)                                                   # 画像 URL: /gradio_api/file=<絶対パス> → /images/...（英字のファイル名）
    def clear():
        for mod in (a, guide):
            for name in dir(mod):
                fn = getattr(mod, name)
                if callable(fn) and hasattr(fn, "cache_clear"): fn.cache_clear()
    clear()
    gr_url = re.compile(r"/gradio_api/file=" + re.escape(quote(app_dir.replace(os.sep, "/"), safe="/:")) + r"/")
    def fix(s):
        s = gr_url.sub("/", s); assert "/gradio_api/" not in s; return s

    regs = sorted(set(a.D["taiwan"]["spots"].region) | set(a.D["japan"]["spots"].region))
    rid = {r: i for i, r in enumerate(regs)}
    out = os.path.join(site_dir, "data", "pages"); n_files = 0; size = 0
    def put(lang, name, html):
        nonlocal n_files, size
        d = os.path.join(out, lang); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f: f.write(fix(html))
        n_files += 1; size += len(html.encode())

    class FakeDate(_dt.date):          # イベント・準備ページの「今月」を切り替えて12か月分作る
        month_override = None
        @classmethod
        def today(cls): return _dt.date(2026, cls.month_override, 15)
    class FakeDT: date = FakeDate; datetime = _dt.datetime
    real_guide_dt = guide.datetime

    for lang in a.LANG_ORDER:
        for reg in regs:
            m = a.mkt_of(reg); i = rid[reg]
            put(lang, f"region-{i}.html", a.build_page(m, lang, ("list", ("region", reg))))
            for k in ("area", "car", "trans"):
                put(lang, f"{k}-{i}.html", a.build_page(m, lang, ("hotel", (reg, "@" + k))))
        for m in ("taiwan", "japan"):
            for k in ("hotels", "cars", "trans"):
                put(lang, f"{m}-{k}.html", a.build_page(m, lang, ("list", (k, ""))))
            guide.datetime = FakeDT
            try:
                for mon in range(1, 13):
                    FakeDate.month_override = mon; clear()
                    put(lang, f"{m}-events-{mon}.html", a.build_page(m, lang, ("list", ("events", ""))))
                    put(lang, f"{m}-prep-{mon}.html", a.build_page(m, lang, ("list", ("prep", ""))))
            finally:
                guide.datetime = real_guide_dt; clear()
    print(f"pages: {n_files} files, {size // 1024 // 1024} MB")

    # ---- スポットごとのホテルページ: ひな形 + 検索語 ----
    real = (a.place_term, a.enc_term)
    a.place_term = lambda m, reg, spot: P_TERM
    a.enc_term = lambda term, cs: P_UTF if cs == "utf-8" else P_EUC
    a.TW_EN[P_REG] = P_REGEN; a.JP_EN_X = None
    hotel_tpl = {}
    try:
        for lang in a.LANG_ORDER:
            hotel_tpl[lang] = {}
            for m in ("taiwan", "japan"):
                en = a.JP_EN if m == "japan" else a.TW_EN; en[P_REG] = P_REGEN
                try: hotel_tpl[lang][m] = fix(a.hotel_page(m, lang, P_REG, P_SPOT))     # build_page はこのあと kb() を通す（ブラウザ側で差し込み後に kb() する）
                finally: en.pop(P_REG, None)
    finally:
        a.place_term, a.enc_term = real; a.TW_EN.pop(P_REG, None)
    for m in ("taiwan", "japan"):
        terms = {}
        for (reg, spot) in a.D[m]["spots"].drop_duplicates(["region", "spot"])[["region", "spot"]].itertuples(index=False):
            t = a.place_term(m, reg, spot)
            terms.setdefault(reg, {})[spot] = [t, a.enc_term(t, "utf-8"), a.enc_term(t, "euc-jp")]
        with open(os.path.join(site_dir, "data", f"hotel_terms_{m}.json"), "w", encoding="utf-8") as f: json.dump(terms, f, ensure_ascii=False, separators=(",", ":"))

    # ---- サイト内検索の索引 ----
    search = dict(idx=[[e["m"], e["reg"], e["rn"], e["cats"], [list(x) for x in e["spots"]]] for e in a.IDX],
                  catn=a.CATN, cwords={m: sorted(v) for m, v in a.CWORDS.items()},
                  var={chr(k): v for k, v in a.VAR.items()})
    with open(os.path.join(site_dir, "data", "search.json"), "w", encoding="utf-8") as f: json.dump(search, f, ensure_ascii=False, separators=(",", ":"))

    # ---- 結果・お気に入り・検索で使う文言とひな形を ui*.json に追記 ----
    up = os.path.join(site_dir, "data", "ui.json"); U = json.load(open(up, encoding="utf-8"))
    for r in regs:
        U["regions"][r]["id"] = rid[r]
        U["regions"][r]["months"] = list(a.SEASON.get(r, ([], []))[0])
        U["regions"][r]["focus"] = [str(x) for x in a.FOCUS.get(r, (50, 50))]      # 写真の主役の位置（f"{fx}%" と同じ書き方）
        U["regions"][r]["theme"] = fix(a.theme_html(a.mkt_of(r), "pc", "list", 3, r, "ja"))     # エリアの写真の背景（言語によらない）
    U["cover_svg"] = {m: [a.cover_svg(m, i) for i in range(1, 6)] for m in ("taiwan", "japan")}
    U["hidx"] = {m: a.HORDER[m] for m in a.HORDER}
    json.dump(U, open(up, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for lang in a.LANG_ORDER:
        lp = os.path.join(site_dir, "data", f"ui_{lang}.json"); L = json.load(open(lp, encoding="utf-8"))
        L["season_rng"] = {r: a.ranges(a.SEASON.get(r, ([], []))[0], lang) for r in regs}
        L["bname"] = {m: {b: a.bname(m, b, lang) for b in set(a.BLOCKS[m].values())} for m in ("taiwan", "japan")}
        L["catname"] = {c[0]: a.catname(lang, c[0]) for c in a.CATS}
        L["cn"] = {m: a.CN[m][lang] for m in a.CN}
        L["srch"] = list(a.SRCH[lang]); L["favx"] = a.FAVX[lang]
        L["lbl_plan"] = {k: v for k, v in a.LBL[lang].items() if k.startswith("plan_")}
        L["first_info_kb"] = a.kn(a.FIRST_INFO[lang])
        L["hotel_tpl"] = hotel_tpl[lang]
        for m in ("taiwan", "japan"):
            t = a.TX(m, lang)
            L["m"][m]["model_note"] = a.model_note(m, lang)
            L["m"][m]["note"] = a.note_html(t)
            L["m"][m]["fav_empty_page"] = fix(a.kb(a.fav_page(m, lang, [])))
        json.dump(L, open(lp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("hotel templates / search index / ui strings: OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
