"""静的サイト版の動作テスト（画面遷移・戻る/進む・再読み込み・入力欄・診断・共有リンク・地図/カテゴリ）。
診断結果は、元の app.py の recommend() が返す HTML と比べる。
使い方: cd site && python -m http.server 8765   （別の端末で）
        python tests/test_ui.py <元アプリのフォルダ（パッチ適用済み）> [http://localhost:8765/]"""
import os, sys, time, json, re, html as H
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from playwright.sync_api import sync_playwright
APP = os.path.abspath(sys.argv[1]); U = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8765/"
NG = []
def ok(c, msg):
    print(("OK  " if c else "NG  ") + msg)
    if not c: NG.append(msg)
def py_top5(m,lang,days,budget,party,first,scores,cur="USD"):
    from load_app import load; a=load(APP)
    h,_=a.recommend(m,lang,days,budget,party,first,*scores,cur=cur)
    regs=[H.unescape(x) for x in re.findall(r'tjNav\(&quot;region\\t(.*?)&quot;\)',h)]
    pcts=re.findall(r'<div class="pct">(\d+%)',h)
    whys=[re.findall(r'<li>(.*?)<b>(\+[\d.]+pt)</b>',blk) for blk in re.findall(r'<div class="whym">(.*?)</ul>',h)]
    spots=[[H.unescape(x) for x in re.findall(r'data-sp="([^"]*)"',blk)] for blk in re.findall(r'<div class="rw">(.*?)<div class="more">',h,re.S)]
    return [(a.rname(r,lang),p) for r,p in zip(regs,pcts)], [[(H.unescape(t),pt) for t,pt in w] for w in whys], spots
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=os.environ.get("CHROME","/usr/bin/google-chrome"))
    pg=b.new_page(viewport=dict(width=1440,height=900), locale="ja-JP")
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type=="error" and "Failed to load resource" not in m.text else None)      # 天気（外部 API・元アプリのサーバー経由の予備経路）の通信エラーは除く
    pg.goto(U); pg.wait_for_selector("#landing",state="visible"); time.sleep(1)
    ok(pg.inner_text("#pick-tw").strip()=="台湾旅行を計画する", "ブラウザの言語(ja)で日本語のトップ")
    pg.evaluate("document.querySelector('.bgfx .slide')._mark=1")
    pg.click("#menuhtml .hlang a:text-is('繁')"); time.sleep(.8)
    ok(pg.evaluate("document.querySelector('.bgfx .slide')._mark===1"), "言語切替で背景スライドを作り直さない")
    ok(pg.inner_text("#pick-tw").strip()!="台湾旅行を計画する", "繁體に切り替わった: "+pg.inner_text("#pick-tw").strip())
    pg.click("#menuhtml .hlang a:text-is('日')"); time.sleep(.8)
    pg.click("#pick-tw"); pg.wait_for_selector("#frame"); time.sleep(.5)
    ok(pg.is_visible("#tbar") and pg.is_visible("#catbox"), "条件画面: 検索・条件・地図・カテゴリが表示")
    pg.go_back(); time.sleep(.8)
    ok(pg.is_visible("#landing"), "ブラウザの戻る → トップ")
    pg.go_forward(); time.sleep(.8)
    ok(pg.is_visible("#frame"), "ブラウザの進む → 条件画面")
    # 入力
    pg.fill("#n-days","7"); pg.press("#n-days","Tab")
    pg.select_option("#partyd select","family")
    pg.click("#firstr label:nth-child(2)")
    pg.fill("input[data-k=budget]","25000")
    pg.locator(".gr-slider[data-k=s0] input[type=range]").fill("5")
    pg.locator(".gr-slider[data-k=s2] input[type=range]").fill("1")
    pg.click("#formcol .label-wrap"); time.sleep(.3)
    ok(pg.is_visible(".gr-slider[data-k=s6]"), "「その他の好み」を開ける")
    pg.locator(".gr-slider[data-k=s6] input[type=range]").fill("5")
    ok(pg.input_value(".gr-slider[data-k=s6] input[type=number]")=="5", "スライダーと数値欄が連動")
    pg.click(".gr-slider[data-k=s6] .reset-button")
    ok(pg.input_value(".gr-slider[data-k=s6] input[type=number]")=="3", "リセットボタンで初期値3")
    pg.locator(".gr-slider[data-k=s6] input[type=range]").fill("4")
    pg.reload(); pg.wait_for_selector("#frame"); time.sleep(1)
    ok(pg.input_value("#n-days")=="7" and pg.input_value("#partyd select")=="family" and pg.input_value("input[data-k=budget]")=="25000", "再読み込みしても条件画面と入力値を復元")
    pg.click("#go"); pg.wait_for_selector("#rescol .regions .rw", timeout=30000); time.sleep(.5)
    names=pg.eval_on_selector_all("#rescol .region .name","els=>els.map(e=>e.textContent)")
    pcts=pg.eval_on_selector_all("#rescol .region .pct","els=>els.map(e=>e.childNodes[0].textContent)")
    whys=pg.eval_on_selector_all("#rescol .whym ul","els=>els.map(u=>[...u.querySelectorAll('li')].map(li=>[li.childNodes[0].textContent,(li.querySelector('b')||{}).textContent]))")
    spots=pg.eval_on_selector_all("#rescol .rw","els=>els.map(r=>[...r.querySelectorAll('.spot .star')].map(n=>n.dataset.sp))")
    sc=[5,3,1,3,3,3,4]+[3]*11
    exp,ew,es=py_top5("taiwan","ja",7,25000,"family","repeat",sc)
    ok(list(zip(names,pcts))==exp, f"診断結果の地域・一致度がPython版と一致 {list(zip(names,pcts))}")
    ok([[tuple(x) for x in w] for w in whys]==ew, "おすすめの理由（文言・+pt）がPython版と一致")
    ok(spots==es, "上位スポットがPython版と一致")
    pg.click("#rescol .share button"); time.sleep(.6)
    ok(not errs, "共有リンクのコピーでエラーが出ない（元アプリでは plan.js の tjCopy に上書きされて動かなかった）")
    pg.reload(); pg.wait_for_selector("#rescol .regions .rw", timeout=30000); time.sleep(.5)
    ok(pg.eval_on_selector_all("#rescol .region .name","els=>els.map(e=>e.textContent)")==names, "結果画面で再読み込み → 同じ結果を表示")
    pg.go_back(); time.sleep(.8)
    ok(pg.is_visible("#tbar") and pg.input_value("#n-days")=="7", "結果から戻る → 条件画面（入力値はそのまま）")
    pg.click("#catbox .cchip >> nth=0"); time.sleep(.6)
    ok(pg.eval_on_selector("#catbox .cres","e=>e.children.length")>0, "カテゴリを押すと地域一覧（plan.js）")
    pg.click("#catbox .cres a >> nth=0"); time.sleep(1.2)
    ok(pg.is_visible("#pagecol .pgcover"), "カテゴリ一覧の地域ボタン（plan.js の tjGo → #bridge）→ エリアページ")
    pg.go_back(); time.sleep(.8)
    pg.click("#rescol .mapcard svg [onclick] >> nth=3", force=True); time.sleep(1.2)
    ok(pg.is_visible("#pagecol .pgcover") and pg.locator("#pagecol .spot").count() > 3, "地図の地域クリック → エリアのスポット一覧")
    ok(pg.locator(".season .mrow i.now").count() == 1, "エリアページ: 今月の印が1つ")
    ok(pg.locator("#navmark[data-stage=list]").count() == 1, "エリアページの目印(navmark)が list")
    pg.click("#pagecol section.cat h3 >> nth=0"); time.sleep(.8)          # カテゴリは閉じているので開く（tjFold）
    ok(pg.locator("#pagecol .spot .star:visible").count() > 0, "カテゴリの見出しを押すと開く")
    pg.locator("#pagecol .spot .star:visible").first.click(); time.sleep(.5)
    ok("1" in pg.text_content("#menuhtml details.menu .mi:nth-child(6)"), "★でお気に入りに追加 → メニューの件数が1")
    star = pg.locator("#pagecol .spot .star:visible").first
    pg.evaluate("([r,s])=>tjNav('hotel\\t'+r+'\\t'+s)", [star.get_attribute("data-reg"), star.get_attribute("data-sp")])      # スポットのホテルページ（画面にボタンは無いが合図は残っている）
    time.sleep(1.2)
    ok(pg.locator("#pagecol .hotelx .hsite").count() >= 8, "スポットのホテル予約サイト一覧")
    pg.go_back(); time.sleep(1); pg.go_back(); time.sleep(1)
    ok(pg.is_visible("#tbar"), "戻る・戻る → 条件画面")
    pg.click("details.menu summary"); time.sleep(.3); pg.click("a.mi:nth-child(6)"); time.sleep(1.2)
    ok(pg.locator("#pagecol .favpg .spot").count() == 1 and pg.locator("#planout").count() == 1, "メニュー → お気に入り・旅程（1件）")
    pg.click("#pagecol .favpg .star"); time.sleep(1)
    ok(pg.locator("#pagecol .favpg .spot").count() == 0, "お気に入りページで★を外すとページを作り直す（空の表示）")
    pg.go_back(); time.sleep(1)
    pg.fill("#tbar input", "温泉"); pg.press("#tbar input", "Enter"); time.sleep(1.5)
    ok(pg.locator("#pagecol .srch .hit").count() > 3, "キーワード検索 → 検索結果ページ")
    pg.go_back(); time.sleep(1)
    pg.click("#menuhtml a.viewbtn"); time.sleep(.6)
    ok(pg.evaluate("!document.getElementById('cssM').disabled"), "スマホ表示に切替")
    pg.click("#menuhtml a.viewbtn"); time.sleep(.6)
    pg.click("details.menu summary"); time.sleep(.3); pg.click("a.mi:nth-child(8)"); time.sleep(.8)
    ok("JAPAN" in pg.inner_text("#p2t"), "メニュー「もう一方の国」→ 日本の条件画面")
    # 共有リンク
    q="?m=japan&d=3&b=12000&c=USD&p=solo&f=1&s="+",".join(["4","2","5","3","1","2"]+["3"]*12)+"&l=zh&v=pc"
    pg2=b.new_page(viewport=dict(width=1440,height=900)); pg2.goto(U+q); pg2.wait_for_selector("#rescol .regions .rw", timeout=30000); time.sleep(.5)
    names=pg2.eval_on_selector_all("#rescol .region .name","els=>els.map(e=>e.textContent)"); pcts=pg2.eval_on_selector_all("#rescol .region .pct","els=>els.map(e=>e.childNodes[0].textContent)")
    exp,_,_=py_top5("japan","zh",3,12000,"solo","first",[4,2,5,3,1,2]+[3]*12)
    ok(list(zip(names,pcts))==exp, f"共有リンク(?m=japan…&l=zh)で結果を表示・Python版と一致 {list(zip(names,pcts))[:2]}…")
    ok(not errs, f"JSエラーなし {errs[:3]}")
    b.close()
sys.exit(1 if NG else 0)
