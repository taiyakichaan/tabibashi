"""元アプリ(Python/Gradio)と静的サイト版の画面を、同じ操作をしてスクリーンショットで比べる。
使い方:
  1) 元アプリを起動:   cd <元アプリ> && PORT=7861 python app.py
  2) 静的サイトを配信: cd site && python -m http.server 8765
  3) python tests/visual_compare.py [--orig http://localhost:7861/] [--static http://localhost:8765/] [--out ref]
背景のスライドショーは時間で写真が変わるため、比較のときは写真を隠してレイアウトだけを比べる。
差が出た行（5画素以上違う行）の数を表示し、どの場面も ALLOW 行以下なら終了コード 0。
（ドロップダウンの文字は、ネイティブの select と元の input の描画差で、日本語・繁体字のとき 1px ずれる。約12行）"""
import argparse, io, os, sys, time
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--orig", default="http://localhost:7861/"); ap.add_argument("--static", default="http://localhost:8765/")
ap.add_argument("--out", default="ref"); ap.add_argument("--wait", type=float, default=3.5); ap.add_argument("--chrome", default="/usr/bin/google-chrome")
ap.add_argument("only", nargs="*")
A = ap.parse_args(); W = A.wait; ALLOW = 15
os.makedirs(A.out, exist_ok=True)
def lang(pg, ch): pg.click(f"#menuhtml .hlang a:text-is('{ch}')")
def nav(pg, msg): pg.evaluate("(m) => window.tjNav(m)", msg)
def favs(pg):           # お気に入りを入れてから再読み込み（どちらも localStorage の tj_favs を読む）
    pg.evaluate("localStorage.setItem('tj_favs', JSON.stringify([['京都府','清水寺'],['京都府','伏見稲荷大社'],['台南市','安平老街'],['北海道','小樽運河']]))")
    pg.reload(); pg.wait_for_selector("#landing", state="visible", timeout=60000); time.sleep(2)
def cur_eur(pg, site):
    if site == "static": pg.select_option("#curc select", "EUR")
    else: pg.click("#curc input"); time.sleep(.6); pg.click("li.item:has-text('EUR')")
SC = {   # 名前: (画面幅, 操作)
 "pc_landing":    (1440, lambda pg, s: None),
 "pc_cond":       (1440, lambda pg, s: pg.click("#pick-tw")),
 "sp_landing":    (390,  lambda pg, s: None),
 "sp_cond":       (390,  lambda pg, s: pg.click("#pick-tw")),
 "ja_landing":    (1440, lambda pg, s: lang(pg, "日")),
 "ja_japan_cond": (1440, lambda pg, s: [lang(pg, "日"), time.sleep(W), pg.click("#pick-jp")]),
 "zh_taiwan_more":(1440, lambda pg, s: [lang(pg, "繁"), time.sleep(W), pg.click("#pick-tw"), time.sleep(W), pg.click("#formcol .label-wrap")]),
 "en_mobileview": (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), pg.click("#menuhtml a.viewbtn")]),
 "back_home":     (1440, lambda pg, s: [pg.click("#pick-jp"), time.sleep(W), pg.click("#home")]),
 "menu_other":    (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), pg.click("details.menu summary"), time.sleep(.5), pg.click("a.mi:nth-child(8)")]),
 # ③ 結果・④⑤ 各ページ（tjNav は元アプリでも静的版でも同じ合図）
 "result":        (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), pg.click("#go")]),
 "sp_result":     (390,  lambda pg, s: [pg.click("#pick-jp"), time.sleep(W), pg.click("#go")]),
 "region":        (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), nav(pg, "region\t台南市")]),
 "region_ja":     (1440, lambda pg, s: [lang(pg, "日"), time.sleep(W), nav(pg, "region\t京都府")]),
 "sp_region":     (390,  lambda pg, s: [nav(pg, "region\t北海道")]),
 "hotel_spot":    (1440, lambda pg, s: [nav(pg, "hotel\t京都府\t清水寺")]),
 "hotel_area":    (1440, lambda pg, s: [lang(pg, "繁"), time.sleep(W), nav(pg, "hotel\t台南市\t@area")]),
 "car":           (1440, lambda pg, s: [nav(pg, "hotel\t沖縄県\t@car")]),
 "trans":         (1440, lambda pg, s: [nav(pg, "hotel\t東京都\t@trans")]),
 "events":        (1440, lambda pg, s: [pg.click("#pick-jp"), time.sleep(W), nav(pg, "menu\tevents")]),
 "prep":          (1440, lambda pg, s: [lang(pg, "日"), time.sleep(W), pg.click("#pick-tw"), time.sleep(W), nav(pg, "menu\tprep")]),
 "hotels_all":    (1440, lambda pg, s: [nav(pg, "menu\thotels")]),
 "cars_all":      (1440, lambda pg, s: [nav(pg, "menu\tcars")]),
 "trans_all":     (1440, lambda pg, s: [pg.click("#pick-jp"), time.sleep(W), nav(pg, "menu\ttrans")]),
 "fav_empty":     (1440, lambda pg, s: [nav(pg, "menu\tfav")]),
 "fav":           (1440, lambda pg, s: [favs(pg), time.sleep(W), nav(pg, "menu\tfav")]),
 "search":        (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), pg.fill("#tbar input", "温泉"), pg.click("#pbtn")]),
 "search_none":   (1440, lambda pg, s: [pg.click("#pick-tw"), time.sleep(W), pg.fill("#tbar input", "xyzxyz"), pg.click("#pbtn")]),
}
bad = 0
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=A.chrome)
    for name in (A.only or list(SC)):
        width, act = SC[name]; imgs = {}
        for site, url in (("orig", A.orig), ("static", A.static)):
            pg = b.new_page(viewport=dict(width=width, height=900 if width > 500 else 844))
            pg.goto(url); pg.wait_for_selector("#landing", state="visible", timeout=60000); time.sleep(2)
            act(pg, site); time.sleep(W)
            # 背景の写真（時間で切り替わる）と天気・台風情報（外部 API。静的サイト版で追加した札も含む）は比べない
            pg.add_style_tag(content=".bgfx .slide,#hero .slide{visibility:hidden !important}.wx .wxbody{visibility:hidden !important;height:40px !important;overflow:hidden !important}.wx .tychip,.wx .typh{display:none !important}"); time.sleep(.3)
            imgs[site] = Image.open(io.BytesIO(pg.screenshot(full_page=True))).convert("RGB"); imgs[site].save(os.path.join(A.out, f"{name}_{site}.png"))
            pg.close()
        O, S = imgs["orig"], imgs["static"]; h = min(O.size[1], S.size[1]); w = min(O.size[0], S.size[0])
        arr = np.array(ImageChops.difference(O.crop((0, 0, w, h)), S.crop((0, 0, w, h))).convert("L")) > 40
        rows = np.where(arr.sum(1) > 5)[0]; same = O.size == S.size and len(rows) <= ALLOW; bad += not same
        print(f"{'OK' if same else 'NG'}  {name:15s} 元={O.size} 静的={S.size} 差のある行={len(rows)}" + (f"（{rows[0]}〜{rows[-1]}）" if len(rows) else ""))
    b.close()
sys.exit(1 if bad else 0)
