"""元アプリ(Python版)の画面部品（固定のHTML・CSS・文言）を、静的サイト用に書き出す。
使い方: python tools/export_ui.py <元アプリのフォルダ> <出力先 site フォルダ>

書き出すもの
  site/css/app_a.css, app_b.css : app.py の CSS 本体（前半・後半。間に画面別 CSS が入る）。extra.css を含む
  site/css/mobile.css           : 「スマホ表示」を選んだときに足す CSS（PC の画面幅でも 430px 幅）
  site/js/plan.js               : 元の plan.js（旅程・カテゴリ一覧などのブラウザ側処理）をそのままコピー
  site/data/ui.json, ui_<lang>.json : 共通部分 / 言語ごとの HTML 部品と文言
     stage[st]            画面別 CSS（landing / cond / result / list / hotel）
     tokens[m|landing|lang]  国の配色・言語のフォント（CSS 変数）
     ui_<l>.json          landlang / howto / brand / sec[3] / first_info / lbl / sl（好みの名前） …
     ui_<l>.json の m[m]       tx（文言辞書）/ menu[pc|mobile] / numhead[4] / p2t / catsearch / map[pc|mobile] / theme[landing|cond]
HTML 部品は app.py の関数の出力そのまま（文言・句点改行も同じ）。画像の URL だけ site からの相対パスに直す。
"""
import json, os, re, shutil, sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from load_app import load, asset_url, ascii_name

NFAV = "__NFAV__"          # お気に入り件数はブラウザ側で差し込む


def strip_style(s):
    s = s.strip()
    assert s.startswith("<style>") and s.endswith("</style>"), s[:40]
    return s[len("<style>"):-len("</style>")]


def main(app_dir, site_dir):
    app_dir, site_dir = os.path.abspath(app_dir), os.path.abspath(site_dir)
    a = load(app_dir)
    a.asset = asset_url(a)                                                   # 画像 URL: /gradio_api/file=<絶対パス> → /images/...（英字のファイル名）
    for f in ("theme_html", "catsearch_html", "map_card", "stage_css"):       # キャッシュ付きの関数は、書き換え前の URL を覚えていないよう空にする
        fn = getattr(a, f)
        if hasattr(fn, "cache_clear"): fn.cache_clear()
    gr_url = re.compile(r"/gradio_api/file=" + re.escape(quote(app_dir.replace(os.sep, "/"), safe="/:")) + r"/")

    def fix(s):
        s = gr_url.sub("/", s)
        assert "/gradio_api/" not in s, s[s.find("/gradio_api/") - 80:][:200]
        return s

    css_dir = os.path.join(site_dir, "css"); os.makedirs(css_dir, exist_ok=True)
    A, B = a.theme_css()
    open(os.path.join(css_dir, "app_a.css"), "w", encoding="utf-8").write(fix(strip_style(A)))
    open(os.path.join(css_dir, "app_b.css"), "w", encoding="utf-8").write(fix(strip_style(B)))
    open(os.path.join(css_dir, "mobile.css"), "w", encoding="utf-8").write(fix(strip_style(a.CSS_M)))
    shutil.copy2(os.path.join(app_dir, "plan.js"), os.path.join(site_dir, "js", "plan.js"))
    # 元の HEAD のうち、お気に入り（★）・絞り込み・折りたたみ・コピーのスクリプトを js/head.js に（plan.js の後に読み込む）
    fav = next(x for x in re.findall(r"<script>(.*?)</script>", a.HEAD, re.S) if "var FAV=" in x)
    fav, n1 = re.subn(r"\n var t=document\.querySelector\('#bridge2 textarea,#bridge2 input'\);if\(!t\)return false;\n var d=.*?return true\}",
                      "\n if(window.tjFavChanged)window.tjFavChanged(FAV.slice());return true}", fav, flags=re.S)          # Gradio への通知 → 静的版の画面へ通知
    fav, n2 = re.subn(r"window\.tjCopy=function\(q,b\)\{", "var _planCopy=window.tjCopy;window.tjCopy=function(q,b){if(typeof q!=='string')return _planCopy&&_planCopy(q);", fav)
    assert n1 == 1 and n2 == 1, (n1, n2)
    open(os.path.join(site_dir, "js", "head.js"), "w", encoding="utf-8").write(
        "/* 元アプリ app.py の HEAD にあるスクリプト（お気に入り・絞り込み・折りたたみ・コピー）。tools/export_ui.py が書き出す。\n"
        "   変更点: (1) お気に入りの変更を Gradio ではなく静的版の画面（window.tjFavChanged）に知らせる\n"
        "   (2) tjCopy は元アプリでは plan.js の同名関数に上書きされ、結果画面の「共有リンクをコピー」が動かなかった。文字列なら共有リンク、要素なら plan.js の処理に振り分ける */\n"
        + fav)

    ui = dict(slide_sec=a.SLIDE_SEC, langs=list(a.LANG_ORDER), all=a.ALL, core=a.CORE,
              stage={st: fix(a._vars(css)) for st, css in a.STAGE.items()},
              tokens={f"{m}|{int(ld)}|{l}": a._tokens(m, ld, l) for m in ("taiwan", "japan") for ld in (False, True) for l in a.LANG_ORDER},
              lang={})
    regs = sorted(set(a.D["taiwan"]["spots"].region) | set(a.D["japan"]["spots"].region))
    ui["regions"] = {r: dict(m=a.mkt_of(r), photo=fix(a.region_photo(r) or ""), pos=a.bgpos(r)) for r in regs}      # 地域カードの写真と表示位置
    for l in a.LANG_ORDER:
        L = dict(landlang=fix(a.landlang_html(l)), howto=fix(a.howto_html(l)), brand=fix(a.brand_html(l)),
                 sec=[fix(a.sec_html(l, i)) for i in range(3)], first_info=a.kn(a.FIRST_INFO[l]),
                 lbl={k: a.LBL[l][k] for k in ("bgt_cur",) if k in a.LBL[l]}, m={},
                 rname={r: a.rname(r, l) for r in regs}, party={v: p[l] for v, p in a.PARTY})
        for m in ("taiwan", "japan"):
            t = a.TX(m, l)
            tx = {k: v for k, v in t.items() if isinstance(v, (str, int, float, list, dict, tuple))}
            L["m"][m] = dict(
                tx=json.loads(json.dumps(tx, ensure_ascii=False, default=str)),
                menu={v: fix(a.menu_html(m, v, l, NFAV)) for v in ("pc", "mobile")},
                numhead=[fix(a.num_head(l, i, m)) for i in range(4)],
                p2t=fix(a.p2t_html(l, m)),
                catsearch=fix(a.catsearch_html(m, l)),
                map={"pc": fix(a.map_card(m, l, False)), "mobile": fix(a.map_card(m, l, True))},
                theme={"landing": fix(a.theme_html(m, "pc", "landing", 1, None, l)), "cond": fix(a.theme_html(m, "pc", "cond", 2, None, l)),
                       "result": fix(a.theme_html(m, "pc", "result", 3, None, l))},
                empty=fix(a.empty_html(m, l)), chead=fix(a.chead_html(m, l)),
            )
        ui["lang"][l] = L
    langs = ui.pop("lang")                                                  # 言語ごとに分けて、表示中の言語だけ読み込む
    for name, obj in [("ui.json", ui)] + [(f"ui_{l}.json", v) for l, v in langs.items()]:
        out = os.path.join(site_dir, "data", name)
        with open(out, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print(name, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
