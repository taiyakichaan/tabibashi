"""天気欄の台風情報（js/typhoon.js）のテスト。気象庁の台風 JSON を模擬データに差し替えて表示を確かめる。
  data: 台風2つ（台湾の近くで接近のおそれ・グアム付近）→ カード2枚・見出し横の札・最接近の行・出典
  none: 活動中の台風なし → 見出しの横に「台風情報なし」 / fail: 取得失敗 → 「台風情報を取得できません」
使い方: cd site && python -m http.server 8765   （別の端末で）
        python tests/test_typhoon.py   （スクリーンショットは ref/ に保存）"""
import json, time, sys, os
from playwright.sync_api import sync_playwright
def spec(no, name_jp, name_en, cat, pos, pres, sus, gust, course, spd, fc, scale="-", inten="強い"):
    out=[{"part":"title","issue":{"JST":"2026-11-17T21:45:00+09:00","UTC":"2026-11-17T12:45:00Z"},"typhoonNumber":no,"name":{"jp":name_jp,"en":name_en},"category":{"jp":"台風","en":cat}},
         {"part":{"jp":"実況"},"advancedHours":0,"category":{"jp":"台風","en":cat},"scale":scale,"intensity":inten,"position":{"deg":pos},"location":"x","course":course,"speed":{"km/h":spd,"kt":"10"},"pressure":pres,
          "maximumWind":{"sustained":{"m/s":sus,"kt":"1"},"gust":{"m/s":gust,"kt":"1"}},"validtime":{"JST":"2026-11-17T21:00:00+09:00"}}]
    for h,p in fc: out.append({"part":{"jp":f"予報　{h}時間後"},"advancedHours":h,"position":{"deg":p},"validtime":{"JST":f"2026-11-{17+h//24:02d}T21:00:00+09:00"}})
    return out
DATA={"targetTc.json":[{"tropicalCyclone":"TC2631","typhoonNumber":"2625","category":"TY","issue":"2026-11-17T21:45:00+09:00"},{"tropicalCyclone":"TC2632","typhoonNumber":"2626","category":"TS","issue":"2026-11-17T21:45:00+09:00"}],
 "TC2631/specifications.json":spec("2625","ウサギ","USAGI","TY",[20.8,123.6],"950","40","60","西北西","15",[(24,[22.3,121.4]),(48,[23.6,119.6]),(72,[25.0,118.5])],scale="大型",inten="非常に強い"),
 "TC2632/specifications.json":spec("2626","マンニィ","MAN-YI","TS",[14.2,146.0],"998","20","30","西","20",[(24,[14.8,143.5]),(48,[15.5,141.0])],inten="-")}
OUT = "ref"; os.makedirs(OUT, exist_ok=True); NG = []
def make_handler(mode):
  def handler(route):
    u=route.request.url.split("/typhoon/data/")[1]
    if mode=="fail": return route.abort()
    if mode=="none": return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body="[]")
    route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(DATA[u],ensure_ascii=False))
  return handler
with sync_playwright() as p:
  b=p.chromium.launch(executable_path=os.environ.get("CHROME","/usr/bin/google-chrome"))
  for mode in ("data","none","fail"):
    handler=make_handler(mode)
    for lang,loc in (("ja","ja-JP"),("zh","zh-TW"),("en","en-US")):
        for name,vp in (("pc",dict(width=1440,height=900)),("sp",dict(width=390,height=844))):
            ctx=b.new_context(viewport=vp, locale=loc, timezone_id="Asia/Tokyo"); pg=ctx.new_page(); errs=[]
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("https://www.jma.go.jp/bosai/typhoon/data/**", handler)
            pg.goto("http://localhost:8765/"); pg.wait_for_selector("#landing",state="visible"); time.sleep(.8)
            title=pg.title()
            pg.evaluate("tjNav('region\\t台南市')"); pg.wait_for_selector("#pagecol .wx"); (pg.wait_for_selector(".wx .typh", timeout=10000) if mode=="data" else time.sleep(2)); time.sleep(.5)
            n=pg.locator(".wx .tyc").count(); chip=pg.locator(".wx .tychip").all_inner_texts()
            el=pg.locator(".wx"); el.scroll_into_view_if_needed(); time.sleep(.3)
            pg.add_style_tag(content=".wx .wxbody{min-height:40px}")
            el.screenshot(path=f"{OUT}/typhoon_{mode}_{lang}_{name}.png")
            want = 2 if mode=="data" else 0
            ok = title=="旅橋-TABIBASHI-" and n==want and len(chip)==1 and not errs
            if mode!="data": ok = ok and pg.locator(f".wx .tychip.{mode}").count()==1        # 台風なし→「台風情報なし」/ 取得失敗→「取得できません」
            if mode=="data":
                ok = ok and pg.locator(".wx .tyc.near").count()==1 and pg.locator(".wx .tyn").count()==1 and pg.locator(".wx .tycr").count()==1
            print("OK " if ok else "NG ", mode, lang, name, "タブ名=",title, "カード=",n, "札=",chip, "JSエラー=",errs)
            if not ok: NG.append((mode,lang,name))
            ctx.close()

  b.close()
print("OK: 台風情報の表示" if not NG else f"NG: {NG}"); sys.exit(1 if NG else 0)
