import functools, urllib.request, urllib.error, time as _time
"""旅行スポットおすすめ分類アプリ (Gradio) — 台湾旅行(日本人向け) / 日本旅行(台湾人向け) をボタンで切替。
環境変数 MARKET は起動時の初期表示のみ (taiwan | japan)。任意: images/<エリア名>.jpg でエリアカードに写真を表示。"""
import os, re, glob, json, html, base64, unicodedata, joblib, numpy as np, pandas as pd, gradio as gr
import rentacar, threading, extra_desc, transport
from brk import kb, kn
from urllib.parse import quote_plus, quote, urlencode, unquote
import datetime
from season import SEASON, TAGS, ranges
import guide
from desc import describe, subtype
from guide import LBL, prep_page, events_for_region, weather_html, budget_block, lux_head, lux_sec, lux_page
from fx import BASE as FXB, cur_of, conv, nice, default_budget, fmt as fmtc
from blocks import BLOCKS

BASE = os.path.dirname(os.path.abspath(__file__))
# 応答をgzip圧縮する（ページ遷移で送るHTMLは 1/6〜1/10 になる。画像・SSEは対象外）。Gradio がアプリを作るときに挟み込む。失敗しても動作には影響しない
try:
    import gradio.routes as _routes
    from starlette.middleware.gzip import GZipMiddleware as _GZip
    class _ImgCache:          # 画像に Cache-Control を付け、ページを移るたびの再確認(304)の通信をなくす
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http": return await self.app(scope, receive, send)
            async def send2(msg):
                if msg.get("type") == "http.response.start" and msg.get("status") == 200:
                    hs = list(msg.get("headers") or [])
                    if any(k.lower() == b"content-type" and v.startswith(b"image/") for k, v in hs) and not any(k.lower() == b"cache-control" for k, v in hs):
                        msg = dict(msg, headers=hs + [(b"cache-control", b"public, max-age=86400")])
                await send(msg)
            await self.app(scope, receive, send2)
    _create_app = _routes.App.create_app
    def _create_app_gz(*a, **k):
        app_ = _create_app(*a, **k)
        try: app_.add_middleware(_ImgCache); app_.add_middleware(_GZip, minimum_size=1024, compresslevel=5)
        except Exception as e: print("gzip:", e)
        return app_
    _routes.App.create_app = staticmethod(_create_app_gz)
except Exception as _e: print("gzip:", _e)
gr.set_static_paths(paths=[os.path.join(BASE, "images")])     # images/ 配下をそのまま配信
QUEUE = os.environ.get("TJ_QUEUE", "0") == "1"                     # False: 画面遷移を待ち行列(SSE)に通さず、1回の通信で返す
SLIDE_SEC = 5                                                # 画像の切替間隔(秒)
START = os.environ.get("MARKET", "taiwan")
CORE = ["food", "nature", "history", "city", "shopping", "nightlife"]
SPOT_COLS = CORE + ["relaxation", "photography"]          # スポットの並べ替えに使うスコア列(1-5)
D = {}
for _m in ("taiwan", "japan"):                       # 自分で学習したscikit-learnモデルを両方読み込む
    _b = joblib.load(f"models/{_m}.joblib"); _s = pd.read_csv(f"data/{_m}_spot_recommendation_detail_url_working.csv")
    D[_m] = dict(model=_b["model"], feats=_b["features"], spots=_s, colmean=_s[SPOT_COLS].mean().to_numpy())
def _load_eval():                       # models/eval_log.txt から検証精度を読む（無ければ表示しない）
    out = {}
    try:
        txt = open("models/eval_log.txt", encoding="utf-8").read()
        for sec in re.split(r"=====\s*", txt)[1:]:
            name = sec.split(":", 1)[0].strip()
            mm = re.search(r"\[テスト\]\s*採用=(\w+)\s+top1=([\d.]+)\s+top3=([\d.]+)\s+top5=([\d.]+)", sec); nn = re.search(r"/\s*(\d+)地域", sec)
            if mm and nn and name in ("taiwan", "japan"): out[name] = dict(algo=mm.group(1), t1=float(mm.group(2)), t3=float(mm.group(3)), t5=float(mm.group(4)), ncls=int(nn.group(1)))
    except Exception: pass
    return out
EVAL = _load_eval()
for _m in D:                            # 「おすすめの理由」用: 学習データの平均的な旅行者（数値は中央値・分類は最頻値）
    _tr = pd.read_csv(f"data/{_m}_traveler_training_synthetic.csv"); _X = _tr.drop(columns=["response_id", "respondent_market", "chosen_region", "data_source"])
    _X["budget_per_day"] = np.log1p(_X["budget_per_day"])
    D[_m]["base"] = {c: (float(_X[c].median()) if pd.api.types.is_numeric_dtype(_X[c]) else _X[c].mode()[0]) for c in D[_m]["feats"]}
KEYS = {"public_transport": "public_transport_importance", "crowd": "crowd_tolerance", "rainy": "rainy_day_importance"}

# ---- スポットの分類（CSVに分類列がないため、スポット名のキーワードで判定。当てはまらないものは「その他」） ----
CATS = [  # key, icon, 日本語, 中文, キーワード（末尾$は後方一致 / 英字は小文字で照合）
    ("themepark", "", "テーマパーク", "主題樂園", "Theme parks", []),
    ("activity", "", "アクティビティ", "體驗活動", "Activities", ["樂園", "ランド", "パーク", "遊樂", "遊園", "ロープウェイ", "纜車", "スキー", "リゾート", "ワールド", "スクウェア", "xpark", "park", "クルーズ", "遊覧", "ラフティング", "カヤック", "ダイビング", "体験", "體驗", "觀光工廠"]),
    ("zoo", "", "動物園・水族館", "動物園・水族館", "Zoos & aquariums", ["動物園", "水族館", "水族園", "海洋館", "サファリ", "牧場", "アクア", "ふれあい"]),
    ("museum", "", "博物館・美術館", "博物館・美術館", "Museums & galleries", ["博物館", "博物院", "美術館", "紀念館", "記念館", "資料館", "科学館", "科學館", "文物", "展示館", "文創", "文化創意", "圖書", "図書館", "藝術", "アート", "ミュージアム", "館$"]),
    ("onsen", "", "温泉・リラックス", "溫泉・放鬆", "Hot springs & relaxation", ["温泉", "溫泉", "湯", "足湯"]),
    ("nightmkt", "", "夜市", "夜市", "Night markets", []),
    ("nightclub", "", "ナイトクラブ", "夜店", "Nightclubs", []),
    ("shrine", "", "神社・寺院", "神社・寺廟", "Shrines & temples", ["神社", "神宮", "大社", "稲荷", "寺", "廟", "宮$", "教堂", "観音", "觀音", "天后", "媽祖"]),
    ("shotengai", "", "商店街", "商店街", "Shopping streets", []),                 # 日本のみ（CSV の primary_category = shopping_street）
    ("oldstreet", "", "老街・商店街", "老街・商店街", "Old streets & shopping streets", []),  # 台湾のみ（同上 + 名前に「老街」）
    ("food", "", "グルメ・市場", "美食・市場", "Food & markets", ["夜市", "市場", "屋台", "横丁", "酒造", "酒廠", "食堂", "料理", "茶", "咖啡", "カフェ", "朝市", "魚市", "漁港", "市集", "小吃", "ビール", "ワイナリー"]),
    ("history", "", "城・史跡・街並み", "古蹟・老街・城堡", "Castles, heritage & old streets", ["城$", "城跡", "城址", "古蹟", "史跡", "遺跡", "砲台", "炮台", "要塞", "古堡", "老街", "街並み", "町並み", "宿場", "関所", "古道", "洋樓", "眷村", "歴史", "陣屋", "古墳", "糖廠", "燈塔", "灯台"]),
    ("nature", "", "自然・景勝", "自然・景觀", "Nature & scenery", ["山", "湖", "滝", "峡", "渓", "溪", "岬", "島", "海岸", "浜", "灘", "公園", "森", "高原", "湿原", "濕地", "湿地", "湧水", "池", "川", "河", "瀑布", "谷", "嶺", "岳", "草原", "花", "步道", "隧道", "潭", "洞", "岩", "海水浴", "丘", "潟", "沼", "沢", "浦", "磐梯", "庭園", "苑$"]),
    ("city", "", "都市・ショッピング", "都會・購物", "City & shopping", ["商圈", "百貨", "モール", "アウトレット", "駅", "車站", "通り", "商店街", "ストリート", "街", "タワー", "塔", "展望", "大樓", "夜景", "ヒルズ", "広場", "廣場"]),
    ("landmark", "", "ランドマーク", "地標", "Landmarks", []),                    # v27: CSV の landmark_flag（タワー・橋・灯台・展望台・像など）。判定は下の _LMK
    ("other", "", "その他の名所", "其他景點", "Other highlights", []),
]
_CS = {"themepark": '<circle cx="12" cy="10" r="6"/><path d="M12 4v12M6 10h12M7.8 5.8l8.4 8.4M16.2 5.8l-8.4 8.4M8 21l4-5 4 5"/>',
       "activity": '<path d="M3 17c3-4 6-4 9 0s6 4 9 0M3 11c3-4 6-4 9 0s6 4 9 0M9 4l3-1 3 1"/>',
       "zoo": '<path d="M4 14c0-4 3-7 8-7s8 3 8 7c0 3-3 5-8 5s-8-2-8-5zM8 11v.1M16 11v.1M10 15h4M6 7l-2-3M18 7l2-3"/>',
       "nightclub": '<path d="M9 3h6l-1 6a3 3 0 01-4 0zM12 12v8M8 20h8M18 4l1 2M20 8l-2 .5"/>',
       "museum": '<path d="M3 9l9-5 9 5z"/><path d="M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18"/>',
       "onsen": '<path d="M8 3c-1.5 1.5 1.5 2.5 0 4M12 3c-1.5 1.5 1.5 2.5 0 4M16 3c-1.5 1.5 1.5 2.5 0 4"/><path d="M4 13h16c0 4-3 7-8 7s-8-3-8-7z"/>',
       "shrine": '<path d="M3 7c4 1.5 14 1.5 18 0M5 11h14M7 7v14M17 7v14"/>',
       "nightmkt": '<path d="M3 9l2-4h14l2 4M3 9h18M5 9v10M19 9v10M3 19h18M9 12v2M12 12v3M15 12v2"/>',
       "shotengai": '<path d="M3 8l9-4 9 4M5 8v12M19 8v12M3 20h18M8 12h3v8M13 12h3v4h-3z"/><path d="M5 8h14"/>',
       "oldstreet": '<path d="M4 20V9l4-3 4 3v11M12 20V9l4-3 4 3v11M2 20h20M7 13h2M15 13h2M8 3v2M16 3v2"/>',
       "food": '<path d="M4 12h16a8 7 0 0 1-16 0z"/><path d="M9 12L16 4M12 12L19 5"/>',
       "history": '<path d="M12 3l5 4H7zM6 7h12l-1.5 5h-9zM5 12h14l1.5 6h-17zM3 21h18"/>',
       "nature": '<path d="M2 20l7-12 4 7 3-4 6 9z"/><circle cx="17" cy="6" r="2"/>',
       "city": '<path d="M5 21V8h6v13M11 21V4h8v17M3 21h18M14 8h2M14 12h2M14 16h2M8 11v.1M8 15v.1"/>',
       "landmark": '<path d="M12 2v3M10 5h4l1 5H9zM9 10h6l2 11H7zM5 21h14M9.5 15h5"/>',
       "other": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>'}
CATS = [(k, f'<svg class="ci" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_CS[k]}</svg>', *rest) for k, _ic, *rest in CATS]
CATICON = {k: ic for k, ic, *_ in CATS}
ACT_RE = ("チームラボ|teamlab|クルーズ|遊覧船|屋形船|観光船|川下り|たらい舟|SUP|スキューバ|ダイビング|シュノーケル|バンジー|ラフティング|カヤック|カヌー|パラグライダー|サーフ|ジップライン|乗馬|気球|キャニオニング|サイクリング|遊船|遊湖船|浮潛|潛水|衝浪|泛舟|獨木舟|滑翔|飛行傘|熱氣球|體驗|体験|ゴルフ|スキー場|ボート|ヨット|ラフト|トレッキング|ツアー|スノーシュー|スカイダイビング|ゴンドラ")
CHAR_RE = ("ジブリ|ポケパーク|poképark|pokepark|ポケモン|サンリオ|ピューロ|ハローキティ|hello kitty|ドラえもん|藤子|ムーミン|アンパンマン|スヌーピー|ミッフィー|トーマス|ハリー・ポッター|ワンピース|ナンジャタウン|ちびまる子|仮面ライダー|ガンダム|レゴ|legoland|キャラクター|ミニオン|ニンテンドー|ゲゲゲ|水木しげる|名探偵コナン|鬼太郎|エヴァ|吉卜力|哆啦|小叮噹|三麗鷗|凱蒂貓|樂高|迪士尼|環球影城|ディズニー|ユニバーサル")
DUP_DROP = {"PokéPark KANTO", "teamLab Planets TOKYO"} | set("""伊万里大川内山 神戸北野異人館街 布引ハーブ園 網走監獄 博物館網走監獄 青岸渡寺 金剛峯寺 湯布院・湯の坪街道 湯布院 大阪中之島美術館x 鹽竈神社 平和記念資料館 脇町うだつの町並み 小便小僧 タオル美術館 松山・坂の上の雲ミュージアム 佐渡・尖閣湾揚島遊園 たらい舟 上野公園 六本木ヒルズ 足利フラワーパーク 華厳ノ滝 佐野厄よけ大師 天草崎津集落 横浜・八景島シーパラダイス 箱根彫刻の森美術館 箱根・大涌谷 氣比神宮 中洲屋台街 桜井二見ヶ浦 会津さざえ堂 角館武家屋敷通り 大館・秋田犬の里 軽井沢・白糸の滝 白糸の滝（軽井沢） 龍宮窟 道の駅小豆島オリーブ公園 小豆島・二十四の瞳映画村 直島・ベネッセハウスミュージアム 直島・地中美術館 高知県立坂本龍馬記念館 四万十・佐田沈下橋 奄美大島・あやまる岬 屋久島・白谷雲水峡 奄美大島・ハートロック 知覧武家屋敷 鳴子温泉郷 花巻温泉郷 隠岐・ローソク島 出雲日御碕灯台
臺中國家歌劇院x 國家歌劇院x 科博館 綠島朝日溫泉x 朝日溫泉 昭和J18 海洋科技博物館 望幽谷 傳統藝術中心 漁人碼頭 十七公里海岸 新竹市玻璃工藝博物館 眷村博物館 GLORIA OUTLETS 華泰名品城 雙心石滬 跨海大橋 芹壁聚落 福正聚落 馬祖酒廠展示館 古坑咖啡 佛陀紀念館 打狗英國領事館 旗后砲台""".split())
PCMAP = {"zoo": "zoo", "aquarium": "zoo", "animal_park": "zoo", "marine_life_center": "zoo", "safari": "zoo", "farm_animal_experience": "zoo", "bird_park": "zoo", "insectarium": "zoo",      # v19以降の動物施設
         "theme_park": "themepark", "themepark_leisure": "themepark", "night_market": "nightmkt", "market": "food",
         "hot_spring": "onsen", "hot_spring_relaxation": "onsen", "religious_site": "shrine", "shrine_temple": "shrine",
         "historic_cultural_site": "history", "heritage_oldtown": "history", "museum": "museum", "art_museum": "museum",
         "zoo_aquarium": "zoo", "experience_activity": "activity", "experience": "activity", "activity_spot": "activity", "night_club": "nightclub",
         "natural_landscape": "nature", "water_coast": "nature", "park_garden": "nature", "island": "nature",
         "shopping_mall": "city", "shopping_area": "city", "city_shopping": "city", "shopping": "city", "outlet_mall": "city", "urban_landmark": "city",
         "transport_industrial": "other", "viewpoint_landmark": "other"}      # other_attraction は名前のキーワード判定
# ---- ランドマーク（v27 CSV の landmark_flag = 1 を基準に、名前の一部一致による誤判定を除く） ----
#  ・商業施設・市場・商店街・博物館・動物園・アクティビティ・寺社など、専用の分類がある施設はそちらのまま（例: 「柳橋中央市場」「天神橋筋商店街」「鎌倉大仏」）
#  ・自然／史跡に分類されていたものは、灯台・タワー・橋など「建造物としての名所」だけをランドマークへ（例: 錦帯橋・眼鏡橋・角島灯台・札幌市時計台。天橋立・塔ノ岳・城跡はそのまま）
#  ・個別の修正は data/catfix.json の "landmark_on"（ランドマークにする） / "landmark_off"（しない）に名前を書く
LMK_KEEP_PC = {"shopping_mall", "shopping_street", "shopping_area", "market", "night_market", "art_museum", "museum", "zoo", "aquarium", "animal_park", "marine_life_center",
               "activity_spot", "experience", "experience_activity", "religious_site", "shrine_temple", "hot_spring", "hot_spring_relaxation", "night_club", "theme_park"}
LMK_KEEP_CAT = {"shrine", "museum", "zoo", "themepark", "food", "shotengai", "oldstreet", "nightmkt", "onsen", "nightclub", "activity"}
LMK_BUILT = r"灯台|燈塔|タワー|大橋|吊橋|吊り橋|つり橋|橋梁|鐵橋|鉄橋|跨海|慈恩塔|時計台|ブリッジ|(?<![山岳])橋$|樓$|塔$"
def _lmk(sp, pc, nm):
    if "landmark_flag" not in sp: return pd.Series(False, index=sp.index)
    lt = sp.get("landmark_type", pd.Series("", index=sp.index)).fillna("")
    base = (sp["landmark_flag"] == 1) & ~pc.isin(LMK_KEEP_PC) & ~sp["cat"].isin(LMK_KEEP_CAT) & ~nm.str.contains(r"山$|岳$|山頂$|鉱山|城$|城跡|城址|城下|城山|城周辺|城博物館|宮跡|の塔$|隧道", regex=True)
    built = nm.str.contains(LMK_BUILT, regex=True)
    oc = sp["cat"].isin(["other", "city"]) & ~((lt == "urban_landmark") & (sp["cat"] == "city"))      # 都市・ショッピングのうち、種類が漠然とした urban_landmark（テラス・ボールパーク等）は除く
    nat = (sp["cat"] == "nature") & built
    his = (sp["cat"] == "history") & built & lt.isin(["bridge", "tower", "lighthouse", "historic_landmark", "monument"])
    return base & (oc | nat | his)
def categorize(name, rel=None):
    n = name.lower()
    for key, ic, ja, zh, en, kws in CATS:
        for k in kws:
            if (n.endswith(k[:-1]) if k.endswith("$") else k in n): return key
    return "other"
# ---- 「自然・景勝」のジャンル（海 / 山 / その他）: 名前のキーワード + CSV の mountain_flag で判定。個別の修正は data/catfix.json の "genre" ----
NGEN = [("sea", "海", "海", "Sea"), ("mountain", "山", "山", "Mountains"), ("other", "その他", "其他", "Other")]
NG_LAKE = r"湖|潭|池|沼"
NG_SEA = r"海|浜|濱|浦$|岬|崎$|鼻$|島|嶼|湾|灣|沙灘|ビーチ|礁|港|半島|石滬|砂丘|沙丘|渦潮"
NG_MTN = r"山$|山頂|山系|山區|岳$|峰|嶺|高原|峠|火口|地獄谷|カルデラ|尖$|古道|カール|室堂|上高地|尾瀬|八幡平|大涌谷|御釜|渓谷|溪谷|峡谷|峡$|峽|渓$|溪$|歩危|大台ヶ原|美ヶ原|太魯閣|阿里山|合歡|清境|武陵|拉拉山|神木|縄文杉|白谷雲水|奥入瀬|秋吉台|カルスト|桜島|草千里"
def nature_genre(nm, mf, fx):
    for g in ("sea", "mountain", "other"):
        if nm in fx.get(g, ()): return g
    if re.search(NG_LAKE, nm) and not re.search(r"海|岬", nm): return "other"     # 湖・池・潭は「その他」（湖の島・湖畔を海にしない）
    if mf or re.search(r"山$|岳$|峰$", nm) and not re.search(r"島$|岬", nm): return "mountain"
    if re.search(NG_SEA, nm): return "sea"
    if re.search(NG_MTN, nm): return "mountain"
    return "other"
# ---- 博物館・美術館 / 動物園・水族館 / アクティビティ のジャンル（「自然」と同じ絞り込みボタンで使う）。個別の修正は data/catfix.json の "subgenre" ----
SUBGEN = {
    "museum":   [("art", "美術館", "美術館", "Art museums"), ("museum", "博物館", "博物館", "Museums")],
    "zoo":      [("zoo", "動物園", "動物園", "Zoos"), ("aquarium", "水族館", "水族館", "Aquariums")],
    "activity": [("exp", "体験", "體驗", "Hands-on"), ("sea", "海", "海", "Sea"), ("mountain", "山", "山", "Mountain"), ("other", "その他", "其他", "Other")],
}
SG_ART = r"美術|藝術|芸術|藝廊|画廊|畫廊|ギャラリー|アート|藝文|美學館|文創|文化創意|彫刻|MIHO|パラミタ|ベネッセ|写真美術|綠美圖"
SG_AQUA = r"水族|シーワールド|マリン|アクア|AQUA|うみ|海|ニフレル|NIFREL|イルカ|ドルフィン|Xpark|átoa|AOAO|SATOUMI|カレッタ|ゴビウス|かにっこ|おさかな|養鱒|潮間帶|護魚|漁場|漁業"
SG_SEA_ACT = r"シーカヤック|シュノーケ|ダイビング|サーフ|浮潛|潛水|帆船|鯨|夜釣|跳島|藍眼淚|衝浪|グラスボート|イルカ|流氷|砕氷|観潮|うずしお"
SG_MTN_ACT = r"ロープウェ|ロープウエ|ゴンドラ|ドラゴンドラ|スキー|スノー|トレッキング|古道|登山|ハイキング|纜車|健行|步道|森林鐵路|トロッコ"
SG_EXP = r"体験|體驗|作り|づくり|打ち|狩り|摘み|見学|発掘|手づくり村|陶芸村|工芸村|宿坊|Experience|Making|Ceremony|DIY|製作|品飲|導覽|採茶|採柿|採草莓"
ACT_SEA_T = {"surfing", "sea_kayak", "scuba_diving", "snorkeling"}; ACT_MTN_T = {"skiing", "hiking", "paragliding", "canyoning", "river_tracing"}
ACT_WATER_T = {"SUP", "kayak", "canoe"}          # 海か湖・川かは名前で判定
def sub_genre(cat, nm, pc, at, ft, fx):
    for g, names in fx.get(cat, {}).items():
        if nm in names: return g
    if cat == "museum": return "art" if pc == "art_museum" or re.search(SG_ART, nm) else "museum"
    if cat == "zoo": return "aquarium" if ft in ("aquarium", "marine_life_center") or re.search(SG_AQUA, nm) else "zoo"
    if cat != "activity": return ""
    lake = re.search(NG_LAKE + r"|琵琶|竹生島|ミシガン", nm) and not re.search(r"海|湾|灣", nm)
    if at in ACT_SEA_T or re.search(SG_SEA_ACT, nm): return "sea"
    if at in ACT_MTN_T or re.search(SG_MTN_ACT, nm): return "mountain"
    if at in ("rafting", "cycling", "bungee"): return "other"
    if re.search(SG_EXP, nm): return "exp"
    if at in ACT_WATER_T: return "sea" if re.search(NG_SEA, nm) and not lake else "other"
    if not lake and re.search(NG_SEA + r"|観光船|観光汽船|港", nm): return "sea"
    if re.search(NG_MTN + r"|山", nm): return "mountain"
    return "other"
for _m, _d in D.items():
    _d["spots"] = _d["spots"][~_d["spots"]["spot"].isin(DUP_DROP)].reset_index(drop=True)      # 表記違いで重複しているスポットを片方だけにする
    _sp = _d["spots"]; _sp["cat"] = [categorize(x) for x in _sp["spot"]]
    _pc = _sp["primary_category"].fillna("") if "primary_category" in _sp else ""
    _nm = _sp["spot"]
    _tp = (_pc.isin(["theme_park", "themepark_leisure"]) | _nm.str.contains("テーマパーク|主題樂園|主題遊樂|主題公園|遊園|スパーランド|ハーモニーランド|ファームランド|ユニバーサル|ディズニー|ハイランド|ラグーナ|ハウステンボス|スペイン村", regex=True)) \
          & ~_nm.str.contains("水族館|サファリ|フラワー|ラベンダー|シーワールド|マリンワールド|メリケン|海王丸|ミューズ|ファームパーク|動物|主題館|こんにゃく|能古島", regex=True)     # 動物園・水族館・花の公園などは含めない
    _sp["cat"] = [PCMAP.get(p, c) for p, c in zip(_pc, _sp["cat"])] if "primary_category" in _sp else _sp["cat"]      # CSV(v15)の分類列を優先。曖昧な分類(その他・体験など)だけ名前のキーワードで補う
    _sp.loc[_nm.str.contains("動物園|動物公園|水族園|水族館|海洋館|サファリ|アクアリウム", regex=True), "cat"] = "zoo"     # 動物園・水族館は博物館にしない
    _act = _nm.str.contains(ACT_RE, regex=True, case=False) | _pc.isin(["activity_spot", "experience_activity", "experience"]) | (_sp.get("activity_primary_type", pd.Series("", index=_sp.index)) == "bungee")      # 湖・島など景勝地は、アクティビティができても「自然」のまま
    _sp.loc[_act & ~_nm.str.contains("動物園|水族館|博物館|美術館|資料館|神社|寺$", regex=True), "cat"] = "activity"     # チームラボ・クルーズ・SUP・ダイビング・バンジー等はアクティビティ
    _sp.loc[_nm.str.contains(CHAR_RE, regex=True, case=False) & ~_nm.str.contains("足湯|空港|ホテル", regex=True), "cat"] = "themepark"     # キャラクター系(ジブリ・ポケモン等)はテーマパーク
    _sp.loc[_nm.str.contains("渋谷スクランブル", regex=True), "cat"] = "other"
    _sp.loc[(_pc == "night_club") | (_sp.get("night_club_flag", 0) == 1 if "night_club_flag" in _sp else False), "cat"] = "nightclub"
    _sp.loc[_nm.str.contains("老街|旧街道|宿場町", regex=True) & _sp["cat"].isin(["city", "other"]), "cat"] = "history"
    _sp.loc[_nm.str.contains("橋$", regex=True) & (_sp["cat"] == "city"), "cat"] = "other"                               # 橋はショッピングにしない
    _sp.loc[_nm.str.contains("前浜|ビーチ|海岸|浜$", regex=True) & (_sp["cat"] == "shrine"), "cat"] = "nature"
    _sp.loc[_tp, "cat"] = "themepark"     # テーマパークは独立した分類
    _sp.loc[_pc == "night_market", "cat"] = "nightmkt"        # 夜市は独立した分類
    _sp.loc[_pc == "outlet_mall", "cat"] = "city"             # アウトレットは他のショッピングと同じ「都市・ショッピング」
    _c = _sp["cat"]                                                                                                          # ---- 最終の見直し(名前による補正) ----
    def _to(rx, new, frm=None):
        msk = _nm.str.contains(rx, regex=True, case=False)
        if frm is not None: msk &= _sp["cat"].isin(frm)
        _sp.loc[msk, "cat"] = new
    _to("水族館|シーワールド|マリンワールド|アドベンチャーワールド|動物|イルカパーク|フォーゲルパーク|ニフレル|うみたまご|ぞうの国|Xpark|海洋館", "zoo", ["themepark", "activity", "city", "other", "nature"])
    _to("フラワーパーク|ラベンダー|ミューズパーク|能古島|メリケン|海王丸|揚島遊園|フラワーワールド|ぐんまフラワー|六義園|渉成園|福州園|ビオスの丘|熱帯植物園|ほしだ園地|東南植物楽園|縮景園|由志園|依水園|好古園|バラ園|オリーブ園|ハーブ園|ガーデン|ラベンダー畑|ファーム富田|大野亀", "nature", ["themepark", "activity", "city", "other"])
    _to("ファームパーク|太陽城|OSAKA WHEEL|スキー場|ロープウェ|ゴンドラ|纜車|海賊船|砕氷船|横須賀軍港|鈴鹿サーキット|鐵道自行車|鐵馬道|自行車|台車", "activity", ["themepark", "city", "other", "nature", "history"])
    _to("こんにゃくパーク|蒸溜所|醸造所|ブルーイング|ウイスキー|酒蔵|うなぎパイ|水産物直売|日曜市|ら・ら・ミュウ|糸満お魚|蚵仔寮漁港", "food", ["themepark", "activity", "city", "other"])
    _to("東京ジョイポリス|東映太秦|琉球村|麗寶樂園|義大遊樂世界|義大世界$|劍湖山|六福村|九族|兒童新樂園|尚順育樂|Flyjoy|小人國|小叮噹|和歌山マリーナシティ", "themepark", ["themepark", "activity", "city", "other", "nature"])
    _to("神田明神|毘沙門堂|寂光院|松尾大社|忠烈祠|孔廟|旗津彩虹教堂|院$|大仏|石仏|伽藍|帝釈天|大師$|瑞鳳殿|五大堂|円通院|喜多院|大聖院", "shrine", ["city", "other"])
    _to("江戸東京たてもの園|適塾|三角西港|哈瑪星鐵道文化園區|高雄燈塔|宿$|町並|保存地区|白壁|南町|祇園|ならまち|御所|反射炉|五稜郭|南京町|内蔵|旧市街|グラバー園|オランダ坂|飛騨の里|房総のむら|明治村|昭和の町|故居|聚落|部落|眷村|古道|洋樓|坑道|書院|總兵署|莒光樓|遺址|大稻埕|司馬庫斯|新瓦屋", "history", ["city", "other"])
    _to("沖縄空手会館|国立天文台|パナソニックミュージアム|だんじり会館|利晶の杜|MIHO|國立臺灣藝術教育館|自來水園區|台灣鐵道館", "museum", ["city", "other"])
    _to("タワー|テレビ塔|展望|スカイツリー|ハルカス|スカイビル|通天閣|秋葉原|銀座|ミッドタウン|神楽坂|VISON|オアシス21|サクラタウン|メッツァ|台北101|西門町|草悟道|EXPOCITY", "city", ["other"])
    _to("海地獄|地獄蒸し|不老溫泉", "onsen", ["city", "other", "nature"])
    _to("Experience|Making|Tea Ceremony|クルーズ|遊覧船|イルカウォッチング", "activity", ["city", "other", "nature"])
    _to("三十三間堂|長春祠|龍虎塔", "shrine", ["other"])
    _to("兼六園|偕楽園|梅園|八幡堀|仙巌園|熱海梅園", "nature", ["other", "city"])
    _to("原爆ドーム|ひめゆりの塔|富岡製糸場|郡上八幡|小布施|尾道|近江八幡|黒壁スクエア|門司港レトロ|崎津集落|やきもの散歩道|甲州夢小路|州廳|市役所|赤崁|樹屋|鹽田|圓樓|將軍府|四四南村|得月樓|擎天廳|鐵堡|北門驛|鼓門", "history", ["other", "city"])
    _to("平泉文化遺産センター|リニア・鉄道館|首都圏外郭放水路|筑波宇宙センター|扇形車庫|可口可樂世界|水里蛇窯|板陶窯", "museum", ["other"])
    _to("岩$|崎$|峠|岬|原$|沼|淵|八海|カール|峡|滝|岳|湿原|群生地|松原|丘|ビューポイント|ビュースポット|農場|牧場|森林|林場|瀑布|水庫|濕地|海岸|海濱|斷崖|沙灘|沙丘|潭|嶼|灣|石滬|尾瀬|鬼押出し|戦場ヶ原|殺生石|浄土平|室堂平|霧ヶ峰|八幡平|仁田峠|展海峰", "nature", ["other"])
    _fx = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "catfix.json"), encoding="utf-8"))      # 全スポットを目視で見直した結果(分類の上書き・重複の除外)
    _sp["cat"] = [_fx["set"].get(n, c) for n, c in zip(_nm, _sp["cat"])]
    _street = (_pc == "shopping_street") | _nm.str.contains("商店街" if _m == "japan" else "老街", regex=False)      # v23: 商店街(日本) / 老街・商店街(台湾)
    _sp.loc[_street & ~_sp["cat"].isin(["nightmkt", "nightclub"]), "cat"] = "shotengai" if _m == "japan" else "oldstreet"
    _sp.loc[(_lmk(_sp, _pc, _nm) & ~_nm.isin(_fx.get("landmark_off", []))) | _nm.isin(_fx.get("landmark_on", [])), "cat"] = "landmark"      # v27: ランドマークを「その他」から独立
    _gf = {g: set(v) for g, v in _fx.get("genre", {}).items()}; _mf = _sp["mountain_flag"].fillna(0).astype(float) if "mountain_flag" in _sp else pd.Series(0.0, index=_sp.index)
    _sp["ngen"] = [nature_genre(n, f == 1, _gf) if c == "nature" else "" for n, f, c in zip(_nm, _mf, _sp["cat"])]
    _sgf = {c: {g: set(v) for g, v in d.items()} for c, d in _fx.get("subgenre", {}).items()}
    _col = lambda k: (_sp[k].fillna("").astype(str) if k in _sp else pd.Series("", index=_sp.index))
    _sub = [sub_genre(c, n, p, a, f, _sgf) for c, n, p, a, f in zip(_sp["cat"], _nm, _col("primary_category"), _col("activity_primary_type"), _col("animal_facility_type"))]
    _sp["ngen"] = [s if c in SUBGEN else g for c, s, g in zip(_sp["cat"], _sub, _sp["ngen"])]      # 博物館・美術館 / 動物園・水族館 / アクティビティ も同じ列（data-g）で絞り込む
    if "swimming_status" in _sp:      # v28: 重複で非表示にする行の海岸データ（遊泳可否・できること）を既存スポットへ引き継ぐ（catfix.json の "beach_from"）
        for _k, _src in _fx.get("beach_from", {}).items():
            _rg, _, _to_n = _k.partition("/"); _dst = (_sp["region"] == _rg) & (_nm == _to_n); _s = _sp[(_sp["region"] == _rg) & (_nm == _src)]
            if _dst.any() and len(_s) and not _sp.loc[_dst, "swimming_status"].notna().any():
                for _c in ("beach_coast_flag", "beach_coast_type", "swimming_status", "swimming_season_note", "beach_activity_types", "beach_source_url"): _sp.loc[_dst, _c] = _s.iloc[0][_c]
    _d["spots"] = _sp[~_nm.isin(_fx["drop"])].reset_index(drop=True)

# ---------------- テーマ・文言 ----------------
TH = {"taiwan": dict(ink="#0b1c1d", deep="#14484a", gold="#c7a15a", bg="#eef1ef", line="#d9dfdb",
                     serif="'Shippori Mincho','Hiragino Mincho ProN','Yu Mincho',serif", sans="'Noto Sans JP','Hiragino Sans','Meiryo',sans-serif"),
      "japan":  dict(ink="#12141f", deep="#232c4f", gold="#bf9d6e", bg="#f1f0f3", line="#dcdae2",
                     serif="'Noto Serif TC','Songti TC','PMingLiU',serif", sans="'Noto Sans TC','PingFang TC','Microsoft JhengHei',sans-serif")}
# ---- 多言語テキスト: 繁體中文(zh) / 日本語(ja) / English(en)。表示は選んだ1言語のみ ----
LANG_ORDER = ("zh", "ja", "en"); SHORT = {"zh": "繁", "ja": "日", "en": "EN"}; LANG_NAMES = {"zh": "繁體中文", "ja": "日本語", "en": "English"}
JA = dict(
    days="旅行日数", menu="メニュー", party="同行者", btn="この条件で診断する", more="もっと細かく指定する", res="あなたに合うエリア", blk="地方ブロック別の相性",
    map="地図", img="写真", site="公式", rsite="エリア公式", match="一致度", vm="スマホ表示", vp="PC表示",
    cond="旅の条件を選ぶ", condsub="日数・予算・好みを入れて、診断ボタンを押してください。", p2title="自分にあう行き先を選ぶ",
    note="", empty="診断ボタンを押すと、ここに結果が出ます。",
    hotel="近くのホテルを検索する", hotel_s="ホテル", allspots="全スポットを見る", back="← 戻る", sph="地名・スポット名で検索", sbtn="検索",
    mtitle="地図から探す", msub="エリアをタップすると、そのエリアのスポット一覧を表示します。", psph="地名・スポット名で検索（例：台北、京都）",
    hres="近くのホテルを検索", hsub="「{spot}」（{reg}）の周辺で宿泊先を探せます。予約サイトを選ぶと、エリア名「{term}」で検索したページが新しいタブで開きます。",
    hdirect="サイト内検索", hgoogle="Google経由でサイト内を検索", hnote="サイトを開くと検索語が自動でコピーされます。検索欄が空のときは貼り付けてください。検索ページの仕様は各サイトの都合で変わることがあります。",
    sres="検索結果", nores="該当するページが見つかりません。", regions="エリア", cnt="{n}件", langlabel="言語 / Language",
    tbl_title="{reg}の観光スポットを探す", tbl_hint="分類名をクリックすると、その分類のスポット一覧が開きます。", flt_title="観光スポットを絞り込む", fold_tip="クリックで開く／閉じる", tbl_cat="分類", tbl_n="件数", tbl_total="合計",
    pagesfound="{p}ページ・{s}件のスポットが見つかりました", sec_pages="該当ページ（エリア）", sec_spots="該当スポット", why_region="エリア名", why_cat="分類", why_spot="スポット", andmore="ほか{n}件")
ZH = dict(
    days="旅遊天數", menu="選單", party="同行者", btn="開始診斷", more="更詳細的設定", res="適合您的地區", blk="各地方區塊的契合度",
    map="地圖", img="照片", site="官網", rsite="地區官網", match="契合度", vm="手機版", vp="電腦版",
    cond="選擇旅行條件", condsub="輸入天數、預算與喜好後，按下診斷按鈕。", p2title="選擇適合自己的目的地",
    note="", empty="按下診斷按鈕後，結果會顯示在這裡。",
    hotel="搜尋附近住宿", hotel_s="住宿", allspots="查看全部景點", back="← 返回", sph="搜尋地名・景點名", sbtn="搜尋",
    mtitle="從地圖尋找", msub="點選地區即可查看該地區的景點清單。", psph="以地名・景點名搜尋（例：台北、京都）",
    hres="搜尋附近住宿", hsub="在「{spot}」（{reg}）周邊尋找住宿。選擇訂房網站後，會以地區名稱「{term}」搜尋並在新分頁開啟。",
    hdirect="站內搜尋", hgoogle="透過 Google 搜尋該網站", hnote="開啟網站時會自動複製搜尋詞，若搜尋欄是空的請直接貼上。各網站的搜尋頁面可能會調整。",
    sres="搜尋結果", nores="找不到符合的頁面。", regions="地區", cnt="{n}處", langlabel="語言 / Language",
    tbl_title="尋找{reg}的觀光景點", tbl_hint="點選分類名稱，即可展開該分類的景點清單。", flt_title="篩選觀光景點", fold_tip="點選展開／收合", tbl_cat="分類", tbl_n="數量", tbl_total="合計",
    pagesfound="找到 {p} 個頁面、{s} 處景點", sec_pages="相關頁面（地區）", sec_spots="相關景點", why_region="地區名稱", why_cat="分類", why_spot="景點", andmore="另有 {n} 處")
EN = dict(
    days="Trip length (days)", menu="Menu", party="Travel party", btn="Find my destinations", more="More preferences", res="Destinations for you", blk="Match by area",
    map="Map", img="Photos", site="Official", rsite="Area official", match="Match", vm="Mobile view", vp="Desktop",
    cond="Choose your trip conditions", condsub="Enter your days, budget and interests, then press the button.", p2title="Find the destination that suits you",
    note="", empty="Press the button to see your results here.",
    hotel="Search hotels nearby", hotel_s="Hotels", allspots="See all spots", back="← Back", sph="Search places or spots", sbtn="Search",
    mtitle="Explore by map", msub="Tap a region to see all of its spots.", psph="Search places or spots (e.g. Taipei, Kyoto)",
    hres="Search hotels nearby", hsub="Find a place to stay around “{spot}” ({reg}). Choose a booking site to open a search for the area “{term}” in a new tab.",
    hdirect="Site search", hgoogle="Search the site via Google", hnote="The search term is copied automatically when you open a site; paste it if the search box is empty. Search pages may change depending on each site.",
    sres="Search results", nores="No matching pages found.", regions="Region", cnt="{n} spots", langlabel="Language",
    tbl_title="Find the sights of {reg}", tbl_hint="Click a category to open its list of spots.", flt_title="Filter the sights", fold_tip="Click to open or close", tbl_cat="Category", tbl_n="Spots", tbl_total="Total",
    pagesfound="Found {p} pages and {s} spots", sec_pages="Matching pages (regions)", sec_spots="Matching spots", why_region="Region name", why_cat="Category", why_spot="Spots", andmore="+{n} more")
JA.update(
    fav_menu="お気に入り・旅程（{n}）", fav_title="お気に入り・旅程リスト", fav_sub="スポット右端の星ボタンで保存した一覧です。このブラウザに保存され、次回も残ります。",
    fav_empty="まだお気に入りがありません。スポット右端の星ボタンを押すと、ここに追加されます。", fav_print="印刷", fav_copy="テキストをコピー", fav_clear="すべて削除", copied="コピーしました", fav_add="お気に入りに追加／解除",
    f_off="スポット公式サイトありのみ", f_cat="すべてのカテゴリー", f_none="条件に合うスポットがありません", f_q="このページ内を絞り込み", sort_def="標準順", sort_name="名前順", sort_off="公式サイト優先", f_shown="{n}件を表示",
    share="この診断結果の共有リンクをコピー", share_hint="条件が入ったURLです。送った相手は同じ診断結果をすぐに開けます。",
    cmp_title="上位3エリアを比べる", cmp_hint="各行でいちばん高い（多い）値を金色で示します。", cmp_match="一致度", cmp_spots="スポット数", cmp_official="公式サイトありのスポット",
    cmp_cats="分類別の件数", cmp_scores="スポットの特徴（平均 1〜5）", cmp_season="ベストシーズン", cmp_now="今月（{m}月）",
    why_title="おすすめの理由", why_none="目立った理由はありません（全体的な傾向による結果です）", why_days="旅行日数 {n}日", why_budget="1日の予算 {n}", why_party="同行者：{p}", why_first="初めての訪問", why_repeat="リピート訪問",
    model_title="このおすすめの仕組み", model1="旅の条件を、学習済みの scikit-learn モデル（{algo}）に入力し、各エリアが選ばれる確率を計算しています。上位5エリアを表示しています。",
    model2="「おすすめの理由」は、その条件を平均的な値に置き換えたとき、そのエリアの一致度が何ポイント下がるかで求めています。",
    model3="検証用データでの精度：1位的中 {t1}（ランダムなら {r1}）／上位3位 {t3}／上位5位 {t5}。",
    fl_q="名前で検索", fl_cat="カテゴリー", fl_sort="表示順", fl_new="最新スポット", new_all="すべて表示", new_only="最新スポットのみ表示", season_title="ベストシーズンの目安", season_note="一般的な気候に基づく目安です。実際の天候やイベントは、公式情報でご確認ください。", season_best="おすすめの月", season_now="今月")
ZH.update(
    fav_menu="收藏・行程（{n}）", fav_title="收藏・行程清單", fav_sub="按下景點右側的星形按鈕即可加入。清單會保存在此瀏覽器，下次開啟仍會保留。",
    fav_empty="目前還沒有收藏。按下景點右側的星形按鈕，就會加到這裡。", fav_print="列印", fav_copy="複製文字", fav_clear="全部刪除", copied="已複製", fav_add="加入／取消收藏",
    f_off="只看有景點官網", f_cat="所有分類", f_none="沒有符合條件的景點", f_q="在此頁面中篩選", sort_def="預設順序", sort_name="依名稱", sort_off="官網優先", f_shown="顯示 {n} 處",
    share="複製此診斷結果的分享連結", share_hint="連結中已包含條件，對方開啟後可直接看到相同的診斷結果。",
    cmp_title="比較前三名地區", cmp_hint="每一列中最高（最多）的數值以金色標示。", cmp_match="契合度", cmp_spots="景點數", cmp_official="有官網的景點",
    cmp_cats="各分類景點數", cmp_scores="景點特色（平均 1–5）", cmp_season="最佳季節", cmp_now="本月（{m}月）",
    why_title="推薦理由", why_none="沒有特別突出的理由（屬於整體傾向的結果）", why_days="旅遊天數 {n} 天", why_budget="每日預算 {n}", why_party="同行者：{p}", why_first="第一次造訪", why_repeat="再訪",
    model_title="推薦的運作方式", model1="將旅行條件輸入已訓練好的 scikit-learn 模型（{algo}），計算各地區被選中的機率，並顯示前 5 名。",
    model2="「推薦理由」是把該條件換成平均值後，觀察該地區的契合度下降了多少個百分點。",
    model3="驗證資料上的準確率：第 1 名命中 {t1}（隨機為 {r1}）／前 3 名 {t3}／前 5 名 {t5}。",
    fl_q="依名稱搜尋", fl_cat="分類", fl_sort="排序", fl_new="最新景點", new_all="全部顯示", new_only="只顯示最新景點", season_title="最佳季節參考", season_note="依一般氣候整理的參考，實際天氣與活動請以官方資訊為準。", season_best="推薦月份", season_now="本月")
EN.update(
    fav_menu="Favorites & itinerary ({n})", fav_title="Favorites & itinerary", fav_sub="Spots you saved with the star button. They are kept in this browser, so they will still be here next time.",
    fav_empty="No favorites yet. Press the star button on a spot to add it here.", fav_print="Print", fav_copy="Copy as text", fav_clear="Clear all", copied="Copied", fav_add="Add / remove favorite",
    f_off="Spot's own official site only", f_cat="All categories", f_none="No spots match your filters", f_q="Filter this page", sort_def="Default order", sort_name="By name", sort_off="Official site first", f_shown="Showing {n}",
    share="Copy a link to this result", share_hint="The link contains your conditions, so anyone who opens it sees the same result.",
    cmp_title="Compare the top 3", cmp_hint="The highest value in each row is shown in gold.", cmp_match="Match", cmp_spots="Number of spots", cmp_official="Spots with an official site",
    cmp_cats="Spots by category", cmp_scores="Spot character (average 1–5)", cmp_season="Best season", cmp_now="This month ({m})",
    why_title="Why this region", why_none="No single standout reason (it reflects your overall profile)", why_days="{n}-day trip", why_budget="Daily budget {n}", why_party="Party: {p}", why_first="First visit", why_repeat="Repeat visit",
    model_title="How the recommendation works", model1="Your conditions are fed to a scikit-learn model trained in this app ({algo}), which computes the probability of each region. The top 5 are shown.",
    model2="“Why this region” measures how many points the match drops when that condition is replaced by an average value.",
    model3="Accuracy on held-out data: top-1 {t1} (chance {r1}) / top-3 {t3} / top-5 {t5}.",
    fl_q="Search by name", fl_cat="Category", fl_sort="Sort", fl_new="New spots", new_all="Show all", new_only="New spots only", season_title="Best season (guide)", season_note="A general guide based on typical climate. Check official sources for actual weather and events.", season_best="Best months", season_now="This month")
SLJ = {"food": "グルメ", "nature": "自然", "history": "歴史", "city": "都市", "shopping": "ショッピング", "nightlife": "ナイトライフ",
       "onsen": "温泉", "beach": "ビーチ", "themepark": "テーマパーク", "museum": "博物館・美術館", "photography": "写真映え",
       "relaxation": "のんびり", "outdoor": "アウトドア", "local_culture": "ローカル文化", "food_market": "屋台・市場",
       "public_transport": "公共交通の使いやすさ", "crowd": "混雑への耐性", "rainy": "雨の日の過ごしやすさ"}
SLZ = {"food": "美食", "nature": "自然", "history": "歷史", "city": "都會", "shopping": "購物", "nightlife": "夜生活",
       "onsen": "溫泉", "beach": "海灘", "themepark": "主題樂園", "museum": "博物館・美術館", "photography": "拍照打卡",
       "relaxation": "悠閒放鬆", "outdoor": "戶外活動", "local_culture": "在地文化", "food_market": "市場・小吃",
       "public_transport": "大眾運輸便利度", "crowd": "對人潮的容忍度", "rainy": "雨天備案重要度"}
SLE = {"food": "Food", "nature": "Nature", "history": "History", "city": "City life", "shopping": "Shopping", "nightlife": "Nightlife",
       "onsen": "Hot springs", "beach": "Beaches", "themepark": "Theme parks", "museum": "Museums & galleries", "photography": "Photo spots",
       "relaxation": "Relaxation", "outdoor": "Outdoor activities", "local_culture": "Local culture", "food_market": "Street food & markets",
       "public_transport": "Public transport access", "crowd": "Tolerance for crowds", "rainy": "Rainy-day options"}
PARTY = [("solo", dict(ja="ひとり", zh="一個人", en="Solo")), ("couple", dict(ja="カップル", zh="情侶", en="Couple")),
         ("friends", dict(ja="友人", zh="朋友", en="Friends")), ("family", dict(ja="家族", zh="家人", en="Family"))]
CS = {"taiwan": {
        "ja": dict(title="台湾へ、心ゆくままに。", first="初めての台湾旅行", budget="1日の予算（円）", land="台湾旅行を計画する", mcond="台湾の行き先を探す", mother="日本旅行を計画する",
                   desc="夜市の香りも、古い街並みのあかりも。あなたの「好き」で選ぶ、とっておきの台湾へ。"),
        "zh": dict(title="台灣之旅，從容自在。", first="第一次去台灣", budget="每日預算（新台幣）", land="計畫台灣之旅", mcond="搜尋台灣的目的地", mother="計畫日本之旅",
                   desc="夜市的香氣、老街的燈火，依您的喜好，挑選專屬的台灣之旅。"),
        "en": dict(title="Taiwan, at your own pace.", first="My first trip to Taiwan", budget="Daily budget", land="Plan a trip to Taiwan", mcond="Find destinations in Taiwan", mother="Plan a trip to Japan",
                   desc="From night-market aromas to lantern-lit old streets — find the Taiwan that fits what you love.")},
      "japan": {
        "ja": dict(title="日本へ、心ゆくままに。", first="初めての日本旅行", budget="1日の予算（円）", land="日本旅行を計画する", mcond="日本の行き先を探す", mother="台湾旅行を計画する",
                   desc="古都の静けさも、街のネオンも。あなたの「好き」で選ぶ、とっておきの日本へ。"),
        "zh": dict(title="前往日本，從容自在。", first="第一次去日本", budget="每日預算（新台幣）", land="計畫日本之旅", mcond="搜尋日本的目的地", mother="計畫台灣之旅",
                   desc="古都的靜謐、街頭的霓虹，依您的喜好，挑選專屬的日本之旅。"),
        "en": dict(title="Japan, at your own pace.", first="My first trip to Japan", budget="Daily budget", land="Plan a trip to Japan", mcond="Find destinations in Japan", mother="Plan a trip to Taiwan",
                   desc="From quiet old capitals to neon-lit streets — find the Japan that fits what you love.")}}
LANGS = {"ja": JA, "zh": ZH, "en": EN}
_TXC = {}
FIRSTTXT = dict(ja=("訪問経験", "2回目以降"), zh=("造訪經驗", "去過（再訪）"), en=("Experience", "I've been before"))
def TX(m, lang):
    """国(m)と言語(lang)に対応する文言辞書（1言語のみ）"""
    k = (m, lang)
    if k not in _TXC:
        t = dict(LANGS[lang]); t.update(CS[m][lang]); t["bval"] = default_budget(m, cur_of(lang))
        t["sl"] = {"ja": SLJ, "zh": SLZ, "en": SLE}[lang]; t["party_ch"] = [(p[lang], v) for v, p in PARTY]
        t["first_lab"], t["first_rep"] = FIRSTTXT[lang]; t["first_ch"] = [(t["first"], "first"), (t["first_rep"], "repeat")]; _TXC[k] = t
    return _TXC[k]

# ---- エリア名・ブロック名の言語別表示（検索や表示用。内部キーはCSVの表記のまま） ----
JP_EN = {"北海道": "Hokkaido", "青森県": "Aomori", "岩手県": "Iwate", "宮城県": "Miyagi", "秋田県": "Akita", "山形県": "Yamagata", "福島県": "Fukushima", "茨城県": "Ibaraki", "栃木県": "Tochigi", "群馬県": "Gunma",
         "埼玉県": "Saitama", "千葉県": "Chiba", "東京都": "Tokyo", "神奈川県": "Kanagawa", "新潟県": "Niigata", "富山県": "Toyama", "石川県": "Ishikawa", "福井県": "Fukui", "山梨県": "Yamanashi", "長野県": "Nagano",
         "岐阜県": "Gifu", "静岡県": "Shizuoka", "愛知県": "Aichi", "三重県": "Mie", "滋賀県": "Shiga", "京都府": "Kyoto", "大阪府": "Osaka", "兵庫県": "Hyogo", "奈良県": "Nara", "和歌山県": "Wakayama",
         "鳥取県": "Tottori", "島根県": "Shimane", "岡山県": "Okayama", "広島県": "Hiroshima", "山口県": "Yamaguchi", "徳島県": "Tokushima", "香川県": "Kagawa", "愛媛県": "Ehime", "高知県": "Kochi", "福岡県": "Fukuoka",
         "佐賀県": "Saga", "長崎県": "Nagasaki", "熊本県": "Kumamoto", "大分県": "Oita", "宮崎県": "Miyazaki", "鹿児島県": "Kagoshima", "沖縄県": "Okinawa"}
TW_EN = {"台北市": "Taipei City", "新北市": "New Taipei City", "基隆市": "Keelung City", "桃園市": "Taoyuan City", "新竹市": "Hsinchu City", "新竹縣": "Hsinchu County", "苗栗縣": "Miaoli County", "台中市": "Taichung City",
         "彰化縣": "Changhua County", "南投縣": "Nantou County", "雲林縣": "Yunlin County", "嘉義市": "Chiayi City", "嘉義縣": "Chiayi County", "台南市": "Tainan City", "高雄市": "Kaohsiung City", "屏東縣": "Pingtung County",
         "宜蘭縣": "Yilan County", "花蓮縣": "Hualien County", "台東縣": "Taitung County", "澎湖縣": "Penghu County", "金門縣": "Kinmen County", "連江縣": "Lienchiang County"}
JP_ZH_EX = {"沖縄県": "沖繩縣", "広島県": "廣島縣", "鹿児島県": "鹿兒島縣"}
def mkt_of(reg): return "japan" if reg in JP_EN else "taiwan"
def rname(reg, lang):
    jp = reg in JP_EN
    if lang == "en": return (JP_EN if jp else TW_EN)[reg]
    if jp: return reg if lang == "ja" else JP_ZH_EX.get(reg, reg.replace("県", "縣"))
    return reg.replace("縣", "県") if lang == "ja" else reg
def rshort(reg, lang):             # 地図ラベル用の短い表記
    if lang == "en": return rname(reg, lang)
    n = rname(reg, lang); return n if (not reg in JP_EN or reg == "北海道") else n[:-1]
BN = {"japan": {"北海道": dict(ja="北海道", zh="北海道", en="Hokkaido"), "東北": dict(ja="東北", zh="東北", en="Tohoku"), "関東": dict(ja="関東", zh="關東", en="Kanto"), "中部": dict(ja="中部", zh="中部", en="Chubu"),
                "近畿": dict(ja="近畿", zh="近畿", en="Kinki"), "中国・四国": dict(ja="中国・四国", zh="中國・四國", en="Chugoku & Shikoku"), "九州・沖縄": dict(ja="九州・沖縄", zh="九州・沖繩", en="Kyushu & Okinawa")},
      "taiwan": {"北部": dict(ja="北部", zh="北部", en="North"), "中部": dict(ja="中部", zh="中部", en="Central"), "南部": dict(ja="南部", zh="南部", en="South"), "東部": dict(ja="東部", zh="東部", en="East"), "離島": dict(ja="離島", zh="離島", en="Outlying islands")}}
def bname(m, b, lang): return BN[m].get(b, {}).get(lang, b)

ALL = CORE + [k for k in SLJ if k not in CORE]
ALLREG = set(D['taiwan']['spots'].region) | set(D['japan']['spots'].region)
OTHER = {"taiwan": "japan", "japan": "taiwan"}

# ---------------- 画像（SVGを自作して埋め込み。外部通信なし） ----------------
def uri(svg): return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

def hero_svg(m):
    stars = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity=".7"/>' for x, y, r in [(120,60,1.5),(380,110,1),(640,40,1.5),(900,90,1),(1350,50,1.5),(1500,130,1),(760,150,1)])
    if m == "taiwan":   # 夕暮れの台北：台北101・山並み・提灯
        tiers = "".join(f'<path d="M{1138+i*3} {240+i*36} h{84-i*6} l-4 34 h-{76-i*6}z"/>' for i in range(8))
        lant = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{y-24}" stroke="#c7a15a" stroke-width="1.5"/><circle cx="{x}" cy="{y}" r="46" fill="url(#l)"/><ellipse cx="{x}" cy="{y}" rx="15" ry="20" fill="#e8893a"/><rect x="{x-8}" y="{y-24}" width="16" height="4" fill="#c7a15a"/>'
                       for x, y in [(1390,110),(1450,190),(1520,100),(1565,215)])
        body = f'''<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#06181a"/><stop offset=".62" stop-color="#14575a"/><stop offset="1" stop-color="#e0b06a"/></linearGradient>
<radialGradient id="l"><stop offset="0" stop-color="#ffd9a0" stop-opacity=".9"/><stop offset="1" stop-color="#ffd9a0" stop-opacity="0"/></radialGradient>
<linearGradient id="m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity=".25"/></linearGradient></defs>
<rect width="1600" height="560" fill="url(#s)"/>{stars}<circle cx="1000" cy="400" r="190" fill="url(#l)"/>
<path d="M0 400 L180 290 L330 360 L520 250 L700 370 L880 300 L1060 380 L1250 280 L1420 350 L1600 300 V560 H0Z" fill="#2a8a84" opacity=".4"/>
<path d="M0 450 L220 360 L400 430 L620 340 L840 440 L1040 380 L1300 450 L1600 390 V560 H0Z" fill="#0f5a5a" opacity=".85"/>
<rect y="380" width="1600" height="130" fill="url(#m)"/>
<g fill="#04191a"><rect x="1177" y="150" width="6" height="90"/><path d="M1180 120 l-3 40 h6z"/>{tiers}</g>
<path d="M0 500 Q300 440 640 490 T1300 480 T1600 470 V560 H0Z" fill="#031213"/>{lant}'''
    else:               # 暮れの富士：富士山・五重塔・月・松
        tiers = "".join(f'<path d="M{750-44+i*6} {330+i*40} h{88-i*12} l8 16 h-{104-i*12}z"/>' for i in range(5))
        body = f'''<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0d1a"/><stop offset=".6" stop-color="#2d2f63"/><stop offset="1" stop-color="#e8a9b4"/></linearGradient>
<radialGradient id="l"><stop offset="0" stop-color="#fff4e6" stop-opacity=".8"/><stop offset="1" stop-color="#fff4e6" stop-opacity="0"/></radialGradient>
<linearGradient id="m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity=".25"/></linearGradient></defs>
<rect width="1600" height="560" fill="url(#s)"/>{stars}<circle cx="1000" cy="130" r="120" fill="url(#l)"/><circle cx="1000" cy="130" r="48" fill="#fff4e6"/>
<path d="M880 560 C1060 330 1210 220 1290 200 C1370 220 1500 330 1640 560Z" fill="#2b3270"/>
<path d="M1208 270 L1290 200 L1372 270 L1346 284 L1318 264 L1290 292 L1262 262 L1236 284Z" fill="#f1eef6"/>
<rect y="400" width="1600" height="130" fill="url(#m)"/>
<path d="M0 470 Q300 410 640 460 T1300 450 T1600 440 V560 H0Z" fill="#1a2042"/>
<g fill="#0c0e1a" transform="translate(330 0)"><rect x="747" y="300" width="6" height="30"/>{tiers}</g>
<path d="M1600 0 V60 M1600 40 q-120 10 -220 70 M1520 55 q-30 40 -60 60 M1440 90 q-20 30 -50 40" stroke="#0c0e1a" stroke-width="9" fill="none" stroke-linecap="round"/>
<g fill="#f6c6d0" opacity=".85"><circle cx="1350" cy="190" r="6"/><circle cx="1180" cy="120" r="5"/><circle cx="1440" cy="260" r="6"/><circle cx="560" cy="200" r="4"/><circle cx="1520" cy="170" r="5"/></g>
<path d="M0 520 Q400 480 900 515 T1600 500 V560 H0Z" fill="#070813"/>'''
    return uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 560" preserveAspectRatio="xMidYMid slice">{body}</svg>')

def cover_svg(m, i):
    c, s = TH[m], i * 90
    return uri(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 220" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c["deep"]}"/><stop offset="1" stop-color="{c["ink"]}"/></linearGradient></defs>'
               f'<rect width="900" height="220" fill="url(#g)"/><circle cx="{410+i*18}" cy="70" r="30" fill="{c["gold"]}" opacity=".8"/>'
               f'<path d="M0 170 L{150+s} 90 L{300+s} 160 L{470+s//2} 70 L650 170 L900 110 V220 H0Z" fill="#fff" opacity=".07"/><path d="M0 200 Q200 150 450 190 T900 180 V220 H0Z" fill="#000" opacity=".28"/></svg>')

def asset(p): return "/gradio_api/file=" + quote(os.path.join(BASE, p).replace(os.sep, "/"), safe="/:")

def region_photo(region):          # images/regions/<エリア名>.jpg があれば写真、なければイラスト
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = f"images/regions/{region}.{ext}"
        if os.path.exists(os.path.join(BASE, p)): return asset(p)
    return None

def hero_images(m):                # images/hero/hero_<market>_<番号>.jpg を番号順に
    fs = glob.glob(os.path.join(BASE, "images", "hero", f"hero_{m}_*"))
    key = lambda f: int(re.search(r"_(\d+)\.", f).group(1)) if re.search(r"_(\d+)\.", f) else 0
    return [asset(os.path.relpath(f, BASE)) for f in sorted(fs, key=key)]

# ---------------- CSS（市場ごとに配色・書体を差し替え） ----------------
CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;700&family=Noto+Serif+TC:wght@500;700&family=Noto+Sans+JP:wght@300;400;500&family=Noto+Sans+TC:wght@300;400;500&family=Cormorant+Garamond:wght@500;600&display=swap');
.gradio-container{--slider-color:@gold@;--color-accent:@deep@;--checkbox-background-color-selected:@deep@;--checkbox-border-color-selected:@deep@;--button-primary-background-fill:@ink@;--button-primary-background-fill-hover:@deep@;--button-primary-text-color:#fff;
 background:@bg@ !important;font-family:@sans@ !important;max-width:none !important;width:100% !important;padding:0 !important;margin:0 !important;color:#1c2526}
.gradio-container>.main,.gradio-container .app{max-width:none !important;padding:0 !important}
.gradio-container *{font-family:inherit}
#topbar{background:@ink@ !important;padding:16px clamp(20px,3vw,56px) !important;gap:0 !important;align-items:center !important;flex-wrap:nowrap !important;justify-content:space-between !important;border-radius:0 !important}
#topbar .btns{display:flex;gap:10px;align-items:center;flex-wrap:nowrap !important}#topbar .btns>*{flex:0 0 auto !important;min-width:0 !important}
#topbar>*{background:transparent !important;border:0 !important;box-shadow:none !important;min-width:0 !important;flex:0 0 auto !important;width:auto !important;padding:0 !important}
.brand,.brand *{color:#fff !important}.brand i{background:@gold@ !important}
.brand{font-family:@serif@ !important;font-size:18px;letter-spacing:.28em;font-weight:500}.brand i{display:inline-block;width:28px;height:1px;background:@gold@;vertical-align:middle;margin:0 12px}
#home,#switch,#view{white-space:nowrap !important;background:transparent !important;border:1px solid @gold@ !important;color:@gold@ !important;border-radius:2px !important;letter-spacing:.12em;font-size:13px;padding:9px 20px !important;font-weight:400}
#home:hover,#home:focus-visible,#switch:hover,#switch:focus-visible,#view:hover,#view:focus-visible{background:@gold@ !important;color:@ink@ !important;outline:none}
#go{border:1px solid @gold@ !important;border-radius:2px !important;letter-spacing:.2em;font-weight:500;padding:14px !important;background:@ink@ !important;color:#fff !important}
#go:hover,#go:focus-visible{background:@gold@ !important;color:@ink@ !important}
#hero{position:relative;margin:-26px -12px 0;height:clamp(380px,54vh,640px);background:@ink@ center/cover no-repeat}
.slide{position:absolute;inset:0;background:@ink@ center 40%/cover no-repeat;opacity:0}
#hero .shade{position:absolute;inset:0;background:linear-gradient(90deg,rgba(0,0,0,.78),rgba(0,0,0,.34) 55%,rgba(0,0,0,.05)),linear-gradient(0deg,rgba(0,0,0,.5),rgba(0,0,0,0) 50%)}
#hero .txt{position:absolute;left:clamp(24px,5vw,110px);bottom:60px;right:24px;color:#fff}
#hero h1{margin:0;font-family:@serif@ !important;font-size:clamp(30px,5.2vw,56px);font-weight:500;letter-spacing:.1em;line-height:1.35;color:#fff}
#hero .rule{display:block;width:72px;height:1px;background:@gold@;margin:22px 0 18px}
#hero p{margin:0;max-width:30em;font-size:clamp(13px,1.8vw,15.5px);line-height:2;font-weight:300;letter-spacing:.06em;color:#f1efe9}
#main{padding:clamp(18px,2.4vw,44px) clamp(20px,3vw,56px) !important;gap:clamp(18px,2vw,36px) !important}
.regions{display:flex;flex-direction:column;gap:22px;margin-bottom:22px}.regions .region{margin-bottom:0;display:grid;grid-template-columns:minmax(230px,30%) 1fr}
.regions .region:first-child{border-color:@gold@;box-shadow:0 0 0 1px @gold@}
.panel{background:#fff !important;border-radius:2px !important;padding:26px 28px !important;border:1px solid @line@ !important;border-top:2px solid @gold@ !important;box-shadow:none !important}
.res-empty{padding:64px 28px;text-align:center;color:#6c7778;background:#fff;border:1px solid @line@;line-height:2;letter-spacing:.05em}
.hd{margin:2px 0 16px;font-family:@serif@ !important;font-size:22px;font-weight:500;letter-spacing:.12em;color:#1c2526;padding-bottom:12px;border-bottom:1px solid @gold@}
.region{background:#fff;margin-bottom:22px;border:1px solid @line@}
.region .cover{min-height:170px;background:@ink@ center/cover;position:relative;display:flex;flex-direction:column;align-items:flex-start;justify-content:space-between;padding:22px 26px;color:#fff}
.region .cover::before{content:"";position:absolute;inset:0;background:linear-gradient(0deg,rgba(0,0,0,.74),rgba(0,0,0,.2) 55%,rgba(0,0,0,.38))}.region .cover>*{position:relative}
.region .rank{font-family:@serif@ !important;font-size:56px;line-height:1;font-weight:500;color:@gold@ !important}.region .name{font-family:@serif@ !important;font-size:30px;font-weight:500;letter-spacing:.08em;line-height:1.2;color:#fff !important}
.region .pct{font-family:@serif@ !important;font-size:34px;color:@gold@;text-align:left;line-height:1}.region .pct small{display:block;font-family:@sans@;font-size:11px;letter-spacing:.14em;color:#fff;opacity:.85;margin-top:6px}
.spots{padding:8px 28px 12px;align-self:center;width:100%}
.spot{display:flex;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid #ece9e2}.spot:last-child{border-bottom:0}
.spot .ic{flex:none;width:40px;height:40px;border-radius:50%;border:1px solid @gold@;display:grid;place-items:center;font-size:18px;filter:grayscale(.45)}
.spot .nm{flex:1;font-weight:500;letter-spacing:.04em;color:#1c2526;line-height:1.5}
.spot a,.spot a:visited{flex:none;font-size:12.5px;letter-spacing:.08em;text-decoration:none !important;padding:7px 14px;border:1px solid @ink@;color:@ink@ !important;background:#fff;border-radius:2px}
.spot a:hover,.spot a:focus-visible{background:@ink@;color:#fff !important;outline:none}
.spot a.alt,.spot a.alt:visited{border-color:#c3c7c4;color:#586264 !important}.spot a.alt:hover{background:#586264;color:#fff !important}
.spot a.off,.spot a.off:visited{background:@ink@;border-color:@ink@;color:#fff !important}.spot a.off:hover{background:@gold@;border-color:@gold@;color:@ink@ !important}
.blk{background:#fff;padding:20px 26px;border:1px solid @line@}.blk h3{margin:0 0 12px;font-family:@serif@ !important;font-size:18px;font-weight:500;letter-spacing:.1em}
.bar{display:flex;align-items:center;gap:14px;margin:12px 0;font-size:13.5px;letter-spacing:.04em;color:#2c383a}.bar .l{width:7em;flex:none}
.bar .t{flex:1;height:2px;background:@line@}.bar .f{display:block;height:2px;background:@gold@}.bar .v{width:3.4em;text-align:right;font-variant-numeric:tabular-nums}
.note{margin:14px 0 28px;font-size:12px;color:#7a8586;text-align:center;letter-spacing:.05em}
.bgfx{position:fixed;inset:0;z-index:-1;overflow:hidden;background:@bg@}
.bgfx .half{position:absolute;top:0;bottom:0;overflow:hidden}.bgfx .half.l{left:0;width:50%}.bgfx .half.r{right:0;width:50%}
.bgfx .veil{position:absolute;inset:0;background:rgba(246,247,245,.52);z-index:2}
.bgfx .div{position:absolute;left:50%;top:8%;bottom:8%;width:1px;background:@gold@;z-index:3}
.bgfx .ttl{position:absolute;left:0;right:0;top:22%;text-align:center;z-index:3;color:#0b1c1d;text-shadow:0 0 18px rgba(255,255,255,.95),0 0 5px rgba(255,255,255,.9)}
.bgfx .ttl b{display:block;font-size:clamp(34px,5.2vw,76px);letter-spacing:.24em;font-weight:500;padding-left:.24em}.bgfx .ttl span{display:block;margin-top:14px;font-size:clamp(13px,1.4vw,18px);letter-spacing:.16em}
.chead{background:rgba(255,255,255,.96);padding:22px 28px 10px;border:1px solid @line@;border-top:2px solid @gold@;border-bottom:0;border-radius:2px 2px 0 0}
.chead h2{margin:0 0 6px;font-family:@serif@ !important;font-size:24px;font-weight:500;letter-spacing:.1em;color:#1c2526}.chead p{margin:0 0 6px;color:#6c7778;font-size:13.5px;letter-spacing:.04em}
.gradio-container{overflow-x:clip !important;overflow-y:visible !important}
#hsearch>*{background:transparent !important;border:0 !important;box-shadow:none !important;padding:0 !important;min-width:0 !important}
#hsearch textarea,#hsearch input{background:rgba(255,255,255,.1) !important;color:#fff !important;border:1px solid rgba(199,161,90,.55) !important;border-radius:2px !important;padding:9px 12px !important;font-size:13.5px !important;box-shadow:none !important}
#hsearch textarea::placeholder,#hsearch input::placeholder{color:rgba(255,255,255,.55)}
#hbtn,#pbtn,#back{white-space:nowrap !important;background:transparent !important;border:1px solid @gold@ !important;color:@gold@ !important;border-radius:2px !important;letter-spacing:.1em;font-size:13px !important;padding:9px 16px !important;min-width:0 !important}
#hbtn:hover,#pbtn:hover,#back:hover{background:@gold@ !important;color:@ink@ !important}
#pbtn,#back{border-color:@ink@ !important;color:@ink@ !important}#pbtn:hover,#back:hover{background:@ink@ !important;color:#fff !important}
.hidden-bridge{position:absolute !important;left:-9999px !important;top:0;width:1px;height:1px;overflow:hidden;opacity:0}
.t2{display:block;font-size:.5em;letter-spacing:.14em;margin-top:.55em;font-weight:400;opacity:.92}
.region{cursor:pointer}.region:hover,.region:focus-visible{border-color:@gold@;outline:none}
.region .more{margin:6px 0 0;padding:12px 0 4px;border-top:1px solid #ece9e2;text-align:center;font-size:13px;letter-spacing:.08em;color:@deep@;font-weight:500}
.spot a.hotel,.spot a.hotel:visited{border-color:@gold@;color:#7a5d22 !important}.spot a.hotel:hover{background:@gold@;color:@ink@ !important}
.spot .rg{display:block;font-weight:400;color:#7a8586;font-size:12px;margin-top:2px}
.pg{max-width:1120px;margin:0 auto;padding:clamp(18px,2.4vw,36px) clamp(16px,3vw,56px) 40px}
.pgcover{min-height:200px;background:@ink@ center/cover;position:relative;display:flex;align-items:flex-end;padding:26px 30px;color:#fff;margin-bottom:22px}
.pgcover::before{content:"";position:absolute;inset:0;background:linear-gradient(0deg,rgba(0,0,0,.85),rgba(0,0,0,.3) 65%,rgba(0,0,0,.4))}.pgcover>*{position:relative}
.pgcover h2{margin:4px 0;font-family:@serif@ !important;font-size:clamp(28px,4vw,46px);font-weight:500;letter-spacing:.1em;color:#fff !important}.pgsub{font-size:12px;letter-spacing:.2em;color:@gold@}.pgcover p{margin:0;font-size:13px;color:#fff}
.cat{background:#fff;border:1px solid @line@;margin-bottom:18px}
.cat h3{margin:0;padding:16px 24px 12px;font-family:@serif@ !important;font-size:18px;font-weight:500;letter-spacing:.1em;border-bottom:1px solid @gold@;display:flex;align-items:center;gap:10px;color:#1c2526}.cat h3 em{margin-left:auto;font-style:normal;font-size:13px;color:#7a8586}.cat .spots{padding:4px 24px 10px;width:auto}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}.chip,.chip:visited{padding:8px 16px;border:1px solid @deep@;color:@deep@ !important;background:#fff;text-decoration:none !important;border-radius:2px;font-size:14px;letter-spacing:.06em}.chip:hover{background:@deep@;color:#fff !important}
.hgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin:18px 0}
.hsite,.hsite:visited{display:block;background:#fff;border:1px solid @line@;border-left:3px solid @gold@;padding:16px 18px;text-decoration:none !important;color:#1c2526 !important;font-weight:500;letter-spacing:.04em}.hsite small{display:block;margin-top:4px;color:#7a8586;font-weight:400;font-size:12px}.hsite:hover{border-color:@gold@;background:#fbfaf6}
.mapcard{background:rgba(255,255,255,.95);border:1px solid @line@;border-top:2px solid @gold@;padding:22px 24px}.mapcard h3{margin:0 0 4px;font-family:@serif@ !important;font-size:22px;font-weight:500;letter-spacing:.1em;color:#1c2526}.mapcard p{margin:0;color:#6c7778;font-size:13.5px}
.tiles{display:grid;gap:4px;margin-top:16px}.tile{display:flex;align-items:center;justify-content:center;min-height:40px;font-size:12.5px;letter-spacing:.02em;border:1px solid rgba(0,0,0,.1);border-radius:2px;cursor:pointer;color:#1c2526;text-align:center;line-height:1.2}.tile:hover,.tile:focus-visible{outline:2px solid @gold@;outline-offset:-1px}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:14px;font-size:12px;color:#586264}.legend i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:5px;vertical-align:-1px;border:1px solid rgba(0,0,0,.12)}
#pagecol{padding:14px clamp(16px,3vw,56px) 0 !important;background:transparent !important}#pagecol>#back{width:auto !important;align-self:flex-start !important;flex:0 0 auto !important}
#topbar{position:fixed !important;top:0;left:0;right:0;height:60px;z-index:100;display:flex !important;flex-wrap:nowrap !important;align-items:center !important;gap:12px !important;padding:0 clamp(12px,2.4vw,40px) !important;background:@ink@ !important;border-radius:0 !important;box-shadow:0 1px 0 rgba(199,161,90,.45)}
#topbar>*{flex:0 0 auto !important}#topbar>#hsearch{flex:1 1 auto !important;max-width:560px;margin-left:8px}#topbar>#menuhtml{margin-left:auto !important;overflow:visible !important}
#menuhtml,#menuhtml *{overflow:visible}
details.menu{position:relative}details.menu summary{list-style:none;cursor:pointer;border:1px solid @gold@;color:@gold@ !important;padding:9px 18px;border-radius:2px;letter-spacing:.1em;font-size:13px;white-space:nowrap;user-select:none}details.menu summary::-webkit-details-marker{display:none}
details.menu[open] summary,details.menu summary:hover{background:@gold@;color:@ink@ !important}
.mlist{position:absolute;right:0;top:calc(100% + 10px);min-width:300px;background:#0f1d1e;border:1px solid @gold@;padding:6px 0;box-shadow:0 18px 50px rgba(0,0,0,.45);z-index:200}
.mlist a,.mlist a:visited{display:block;padding:13px 20px;color:#fff !important;text-decoration:none !important;font-size:13.5px;letter-spacing:.06em;border-bottom:1px solid rgba(199,161,90,.25)}.mlist a:last-child{border-bottom:0}.mlist a:hover{background:@gold@;color:@ink@ !important}
#home{white-space:nowrap !important;background:transparent !important;border:1px solid @gold@ !important;color:@gold@ !important;border-radius:2px !important;letter-spacing:.08em;font-size:13px !important;padding:9px 16px !important;min-width:0 !important}#home:hover{background:@gold@ !important;color:@ink@ !important}
.spot{display:grid;grid-template-columns:40px minmax(140px,1fr) minmax(0,max-content);align-items:center;gap:8px 14px;padding:12px 0;border-bottom:1px solid #ece9e2}.spot:last-child{border-bottom:0}
.spot .nm{min-width:0;overflow-wrap:anywhere}.spot .acts{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;max-width:min(430px,62%)}.spot .acts a{white-space:nowrap}
.rw{container-type:inline-size;min-width:0}.cat{container-type:inline-size}
.regions .region{display:grid;grid-template-columns:minmax(210px,28%) minmax(0,1fr);margin-bottom:0}.region .spots,.region .cover{min-width:0}.region .name{overflow-wrap:anywhere}
@container (max-width:900px){.region{grid-template-columns:1fr !important}.region .cover{min-height:150px !important;padding:16px 20px}.region .rank{font-size:40px}}
@container (max-width:640px){.spot{grid-template-columns:40px minmax(0,1fr)}.spot .acts{grid-column:1/-1;justify-content:flex-start;max-width:none}}
.bgfx .ttl{top:auto !important;bottom:calc(50% + 84px) !important}
.bgfx .ttl b{font-size:clamp(30px,min(5.2vw,9vh),76px)}.bgfx .ttl span{font-size:clamp(12px,min(1.4vw,2.3vh),18px);line-height:1.7}
.bgfx .ttl,#pick-tw,#pick-jp{font-family:"Times New Roman",Times,"Cormorant Garamond","Shippori Mincho","Noto Serif TC","Hiragino Mincho ProN","Yu Mincho","MS PMincho",serif !important}
.jmap{display:block;width:100%;max-height:min(82vh,820px);margin:12px auto 0}.pf{cursor:pointer;outline:none}.pf path{stroke:#fff;stroke-width:.9;stroke-linejoin:round}.pf:hover path,.pf:focus path{fill:@gold@ !important}
.lb{text-anchor:middle;fill:#1c2526;pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:2.6px;stroke-linejoin:round;opacity:0;font-weight:500}.lb.al{opacity:1}.pl{cursor:pointer}.pl:hover .lb{fill:#8a6a2c}.ld{fill:none;stroke:#6f7c7d;stroke-width:.7;pointer-events:none}.ldd{fill:#6f7c7d;pointer-events:none}.pf:hover .lb,.pf:focus .lb{opacity:1}
.inset{fill:none;stroke:#9aa5a6;stroke-width:1;stroke-dasharray:4 3;pointer-events:none}
#hero h1 .t2{color:#fff !important}
.p2title{text-align:center;padding:clamp(16px,3.4vh,36px) 16px 0;position:relative;z-index:2}
.p2title h1{margin:0;font-family:@serif@ !important;font-size:clamp(24px,3.2vw,42px);font-weight:500;letter-spacing:.14em;color:@ink@ !important;text-shadow:0 0 22px rgba(255,255,255,.95),0 0 6px rgba(255,255,255,.9)}
.p2title i{display:block;width:72px;height:1px;background:@gold@;margin:14px auto 0}
.cattable{background:#fff;border:1px solid @line@;margin:0 0 20px;padding:18px 24px 14px}
.cattable h3{margin:0 0 4px;font-family:@serif@ !important;font-size:17px;font-weight:500;letter-spacing:.1em;color:#1c2526}.cattable p{margin:0 0 10px;font-size:12.5px;color:#7a8586}
.cattable table{width:100%;border-collapse:collapse}.cattable th{text-align:left;font-size:12px;letter-spacing:.12em;font-weight:500;color:#7a8586;padding:8px 6px;border-bottom:1px solid @gold@}
.cattable td{padding:0;border-bottom:1px solid #ece9e2;font-size:14.5px;color:#1c2526}.cattable td.n,.cattable th.n{text-align:right;width:90px;font-variant-numeric:tabular-nums;padding-right:6px}
.cattable td a,.cattable td a:visited{display:block;padding:11px 6px;color:#1c2526 !important;text-decoration:none !important}.cattable tr.row:hover td{background:#fbfaf6}.cattable td a:hover{color:@deep@ !important}.cattable td.n{padding:11px 6px}.cattable tfoot td{border-bottom:0;font-weight:500;color:#586264;padding:11px 6px}
.cat{scroll-margin-top:calc(var(--hh,60px) + 14px)}
.mlang{padding:12px 20px 14px;border-top:1px solid rgba(199,161,90,.25);color:#cfd7d8;font-size:12px;letter-spacing:.08em}.mlang b{display:block;margin-bottom:8px;font-weight:500;color:@gold@}
.mlang a,.mlang a:visited{display:inline-block !important;padding:6px 10px !important;margin:0 6px 6px 0;border:1px solid rgba(199,161,90,.55) !important;border-radius:2px;color:#fff !important;font-size:12.5px !important}.mlang a.on{background:@gold@;color:@ink@ !important}
.landlang{position:fixed;top:14px;right:18px;z-index:20;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.landlang a,.landlang a:visited{padding:7px 12px;border:1px solid @gold@;color:#fff !important;background:rgba(11,28,29,.78);text-decoration:none !important;font-size:12.5px;letter-spacing:.08em;border-radius:2px;font-family:"Times New Roman",Times,"Shippori Mincho","Noto Serif TC",serif}.landlang a.on,.landlang a:hover{background:@gold@;color:#0b1c1d !important}
.hitgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin:0 0 22px}
.hit{background:#fff;border:1px solid @line@;border-left:3px solid @gold@;padding:16px 18px;cursor:pointer;min-width:0}.hit:hover{border-color:@gold@}
.hit h4{margin:0 0 2px;font-family:@serif@ !important;font-size:19px;font-weight:500;letter-spacing:.06em;color:#1c2526}.hit .cn{font-size:11.5px;letter-spacing:.14em;color:@gold@}
.hit .why{margin-top:8px;font-size:12.5px;color:#586264;line-height:1.8;overflow-wrap:anywhere}.hit .why b{font-weight:500;color:#1c2526}
.sec{margin:6px 0 12px;font-family:@serif@ !important;font-size:18px;font-weight:500;letter-spacing:.1em;color:#1c2526}.sum{margin:0 0 16px;color:#586264;font-size:13.5px}
.pgcover{min-height:clamp(200px,24vw,320px) !important}
.p2title{padding-bottom:22px !important}
#p2t{position:relative;z-index:5;margin-top:60px !important;background:transparent !important;border:0 !important}#p2t .p2title{padding-top:clamp(22px,4vh,44px) !important}
.hlang{display:inline-flex;gap:4px;margin-right:12px;vertical-align:middle}.hlang a,.hlang a:visited{display:inline-block;padding:8px 11px;border:1px solid @gold@;color:#fff !important;font-size:12.5px;text-decoration:none !important;border-radius:2px;letter-spacing:.06em}.hlang a.on{background:@gold@;color:@ink@ !important}
.hm{display:flex !important;align-items:center;white-space:nowrap;gap:0}.hm>*{flex:0 0 auto}
.pg>.hd,.pg>.sum,.pg>h3.sec{text-shadow:0 0 14px rgba(255,255,255,.95),0 0 4px rgba(255,255,255,.9)}
.cattable table,.cattable th,.cattable td,.cattable tr{border:0 !important;background:transparent !important}.cattable th{border-bottom:1px solid @gold@ !important}.cattable td{border-bottom:1px solid #ece9e2 !important}.cattable tfoot td{border-bottom:0 !important}
.cattable td,.cattable td a,.cattable th{text-align:left !important}.cattable td.n,.cattable th.n{text-align:right !important}
/* --- 2ページ目: 縦3段（検索 → 条件 → 地図）。条件は広い画面で2列に並べる --- */
#condbox>.form{display:grid !important;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr)) !important;gap:14px clamp(20px,3vw,48px) !important;width:100% !important;flex:0 0 auto !important}
#condbox>.form>*{min-width:0 !important}#condbox>*{min-width:0 !important}
#rescol .mapcard{max-width:820px;margin:0 auto}
/* --- スポット行: アイコン列・名前・4つのボタン枠を固定。公式が無い行は空枠でホテルの位置を揃える --- */
.spot{display:grid !important;grid-template-columns:40px minmax(120px,1fr) 56px 64px 96px 96px 34px !important;column-gap:8px !important;row-gap:8px;align-items:center}
.spot .nm{grid-column:2}.spot .acts{display:contents !important}
.spot .acts>*{width:100%;min-width:0;box-sizing:border-box;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:7px 4px !important;font-size:12px !important;letter-spacing:.04em !important}
.spot .acts>.ph{display:block;height:1px}
@container (max-width:700px){
 .spot{grid-template-columns:40px minmax(0,.8fr) minmax(0,.8fr) minmax(0,1.3fr) minmax(0,1.3fr) 34px !important;column-gap:6px !important}
 .spot .ic{grid-row:1;grid-column:1}.spot .nm{grid-column:2/6;grid-row:1}.spot .star{grid-column:6;grid-row:1}
 .spot .s-map{grid-column:2}.spot .s-img{grid-column:3}.spot .s-site,.spot .ph{grid-column:4}.spot .s-hotel{grid-column:5}
}
@media(max-width:560px){.spot .acts>*{font-size:11.5px !important;padding:7px 2px !important;letter-spacing:0 !important}}
/* --- お気に入り --- */
.spot .star{width:34px !important;height:34px !important;min-width:0 !important;padding:0 !important;margin:0 !important;border:1px solid #cfd3cf !important;background:#fff !important;color:#c9cdc9 !important;border-radius:50% !important;cursor:pointer;font-size:16px !important;line-height:1 !important;box-shadow:none !important;transition:all .15s}
.spot .star:hover{border-color:@gold@ !important;color:@gold@ !important}.spot .star.on{background:@gold@ !important;border-color:@gold@ !important;color:#fff !important}
.spot.hide,.cat.hide{display:none !important}
.favtools{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}.favtools button{padding:9px 16px;border:1px solid @ink@;background:#fff;color:@ink@;font-size:13px;letter-spacing:.06em;cursor:pointer;border-radius:2px}.favtools button:hover{background:@ink@;color:#fff}
/* --- 絞り込みバー --- */
.tools{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;background:#fff;border:1px solid @line@;border-top:2px solid @gold@;padding:12px 18px;margin:0 6px 18px}
.tools .chk{display:flex;gap:6px;align-items:center;font-size:13.5px;color:#1c2526;cursor:pointer}.tools input[type=search]{flex:1 1 180px;min-width:0;padding:8px 10px;border:1px solid #cfd3cf;border-radius:2px;font-size:13.5px;background:#fff;color:#1c2526}
.tools select{padding:8px 10px;border:1px solid #cfd3cf;border-radius:2px;font-size:13.5px;background:#fff;color:#1c2526}.tools .f-n{margin-left:auto;font-size:12.5px;color:#7a8586}
/* --- ベストシーズン --- */
.season{background:#fff;border:1px solid @line@;border-top:2px solid @gold@;padding:20px clamp(18px,3vw,32px);margin:0 6px 22px}
.season h3{margin:0 0 12px;font-family:@serif@ !important;font-size:17px;font-weight:500;letter-spacing:.12em;color:#1c2526}
.season .mrow{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:4px}.season .mrow i{display:block;text-align:center;padding:9px 0;background:#eef0ee;color:#8a9394;font-style:normal;font-size:12px;border-radius:2px;position:relative}
.season .mrow i b{font-weight:500}.season .mrow i.on{background:@gold@;color:#fff}.season .mrow i.now{outline:2px solid @ink@;outline-offset:1px}
.season .best{margin:12px 0 4px;font-size:14px;color:#1c2526}.season .best span{color:@gold@;letter-spacing:.14em;font-size:12px;margin-right:8px}.season .best em{font-style:normal;margin-left:14px;font-size:12px;color:#7a8586}
.season ul{margin:8px 0 0;padding-left:1.2em;font-size:13px;color:#3d4a4b;line-height:1.9}.season .sn{margin:10px 0 0;font-size:11.5px;color:#8a9394}
/* --- 結果: おすすめの理由 --- */
.whym{padding:12px 4px 8px;font-size:13px;color:#3d4a4b;border-bottom:1px solid #ece9e2;margin-bottom:2px}.whym span{font-size:11.5px;letter-spacing:.16em;color:@gold@}.whym ul{margin:4px 0 0 !important;padding:0 !important;list-style:none !important}
.whym li{display:flex;gap:10px;align-items:baseline;padding:2px 0 !important;margin:0 !important}.whym li b{font-weight:500;color:#1c6b5a;font-size:12px}.whym li.none{color:#8a9394}

/* --- 結果: 上位3エリアの比較表（ダークパネル） --- */
.cmp{position:relative;background:linear-gradient(155deg,#0b1c1d 0%,#12302f 100%);border:1px solid @gold@;outline:1px solid rgba(199,161,90,.45);outline-offset:5px;margin:30px 6px 26px;padding:28px clamp(16px,3vw,40px) 22px;color:#fff;box-shadow:0 24px 60px rgba(0,0,0,.3)}
.cmp h3{margin:0 0 4px;text-align:center;font-family:@serif@ !important;font-size:clamp(18px,2vw,22px);font-weight:500;letter-spacing:.2em;color:@gold@}.cmp>p{margin:0 0 16px;text-align:center;font-size:12.5px;color:#b9c4c3}
.cmpwrap{overflow-x:auto}.cmp table{width:100%;border-collapse:collapse;min-width:420px}.cmp th,.cmp td{padding:11px 10px;text-align:center;font-size:14px;border:0 !important;border-bottom:1px solid rgba(255,255,255,.1) !important;color:#fff !important;background:transparent !important}
.cmp thead th{color:@gold@ !important;font-family:@serif@ !important;font-size:15.5px;letter-spacing:.1em;border-bottom:1px solid @gold@;font-weight:500}.cmp td.l{text-align:left;color:#d6dedd !important;font-size:13px;letter-spacing:.05em;white-space:nowrap}
.cmp td.best{color:@gold@ !important;font-weight:600}.cmp tr.sub th{text-align:left;padding:16px 10px 6px;font-size:11px;letter-spacing:.22em;color:@gold@ !important;border-bottom:1px solid rgba(199,161,90,.35);font-weight:500}
.cmp .sc{display:inline-block;width:44px;height:5px;background:rgba(255,255,255,.18);margin-right:8px;vertical-align:middle;border-radius:3px;overflow:hidden}.cmp .sc i{display:block;height:100%;background:@gold@}
/* --- 結果: 共有リンク / モデル説明 --- */
.share{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin:0 6px 22px}.share button{padding:11px 20px;border:1px solid @gold@;background:#fff;color:#1c2526;font-size:13.5px;letter-spacing:.06em;cursor:pointer;border-radius:2px}.share button:hover{background:@gold@;color:@ink@}.share small{color:#6c7778;font-size:12px}
.modelnote{background:#fff;border:1px solid @line@;border-left:3px solid @gold@;padding:12px 18px;margin:0 6px 18px;font-size:13px;color:#3d4a4b;line-height:1.8}.modelnote summary{cursor:pointer;color:#1c2526;letter-spacing:.08em}.modelnote p{margin:8px 0 0}
@media print{#topbar,.bgfx,.favtools,.star,.acts,#navmark,.hlang,footer{display:none !important}.spot{grid-template-columns:40px 1fr !important}body,.gradio-container{background:#fff !important}.pg .cat,.cat{break-inside:avoid;box-shadow:none}}

/* --- 4ページ目: 背景のエリア写真を全体表示（余白はぼかした同写真） --- */
.bgfx .blurfill{background-size:cover !important;background-position:center !important;filter:blur(26px) saturate(1.1);transform:scale(1.18)}
.bgfx .whole{background-size:contain !important;background-repeat:no-repeat !important;background-position:center !important}
/* --- エリアページ: 分類別の件数表（高級感のあるダークパネル） --- */
.pg .cattable{position:relative;background:linear-gradient(155deg,#0b1c1d 0%,#12302f 100%) !important;border:1px solid @gold@ !important;outline:1px solid rgba(199,161,90,.45);outline-offset:5px;margin:8px 6px 30px !important;padding:30px clamp(20px,3vw,44px) 22px !important;box-shadow:0 24px 60px rgba(0,0,0,.35);color:#fff}
.pg .cattable::before{content:"◆";position:absolute;top:-11px;left:50%;transform:translateX(-50%);padding:0 12px;background:#12302f;color:@gold@;font-size:13px;line-height:20px}
.pg .cattable h3{color:@gold@ !important;text-align:center;font-size:clamp(18px,2vw,22px) !important;letter-spacing:.2em !important;margin:0 0 6px !important}
.pg .cattable p{text-align:center;color:#b9c4c3 !important;margin:0 0 18px !important}
.pg .cattable table{border-top:1px solid rgba(199,161,90,.6) !important}
.pg .cattable th{color:@gold@ !important;border-bottom:1px solid rgba(199,161,90,.35) !important;font-size:11px !important;letter-spacing:.24em !important;padding:12px 8px !important}
.pg .cattable td{color:#fff !important;border-bottom:1px solid rgba(255,255,255,.1) !important;font-size:15.5px !important}
.pg .cattable td a,.pg .cattable td a:visited{color:#fff !important;padding:15px 8px !important;position:relative;letter-spacing:.08em;transition:padding .18s,color .18s}
.pg .cattable td a::after{content:"→";position:absolute;right:6px;color:@gold@;opacity:0;transition:opacity .18s}
.pg .cattable tr.row:hover td{background:rgba(199,161,90,.12) !important}.pg .cattable td a:hover{color:@gold@ !important;padding-left:16px !important}.pg .cattable td a:hover::after{opacity:1}
.pg .cattable td.n{font-family:@serif@ !important;font-size:24px !important;color:@gold@ !important;width:100px;padding-right:28px !important}
.pg .cattable tfoot td{color:@gold@ !important;font-family:@serif@ !important;letter-spacing:.16em;padding:16px 8px 4px !important;border-top:1px solid @gold@ !important;border-bottom:0 !important}
.pg .cattable tfoot td.n{font-size:28px !important;color:#fff !important}

/* === 文字の可読性: 写真の上の文字は白＋影、暗めのグラデーションで背景と同化させない === */
.pgcover::before{background:linear-gradient(0deg,rgba(0,0,0,.9),rgba(0,0,0,.6) 50%,rgba(0,0,0,.3)) !important}
.pgcover .pgsub{color:#f1d9a0 !important;text-shadow:0 1px 8px rgba(0,0,0,.95),0 0 2px rgba(0,0,0,.9)}
.pgcover h2{color:#fff !important;text-shadow:0 2px 14px rgba(0,0,0,.9),0 0 3px rgba(0,0,0,.8)}
.pgcover p{color:#fff !important;opacity:1 !important;text-shadow:0 1px 8px rgba(0,0,0,.95),0 0 2px rgba(0,0,0,.9);font-size:14px !important}
.region .cover::before{background:linear-gradient(0deg,rgba(0,0,0,.88),rgba(0,0,0,.5) 55%,rgba(0,0,0,.42)) !important}
.region .rank{color:#f1d9a0 !important;text-shadow:0 2px 10px rgba(0,0,0,.85)}.region .name{text-shadow:0 2px 12px rgba(0,0,0,.9),0 0 3px rgba(0,0,0,.8)}
.region .pct{color:#f1d9a0 !important;text-shadow:0 2px 10px rgba(0,0,0,.85)}.region .pct small{color:#fff !important;opacity:1 !important;text-shadow:0 1px 6px rgba(0,0,0,.9)}
/* === 分類別の件数: コンパクト版 === */
.pg .cattable{padding:20px clamp(16px,2.6vw,34px) 10px !important;margin:6px 6px 20px !important}
.pg .cattable h3{font-size:clamp(15px,1.6vw,18px) !important;margin:0 0 2px !important}.pg .cattable p{font-size:11.5px !important;margin:0 0 10px !important}
.pg .cattable th{padding:6px 8px !important}.pg .cattable td{font-size:14px !important}
.pg .cattable td a,.pg .cattable td a:visited{padding:8px 8px !important}
.pg .cattable td.n{font-size:18px !important;padding-right:20px !important;width:80px}
.pg .cattable tfoot td{padding:10px 8px 2px !important;font-size:13px !important}.pg .cattable tfoot td.n{font-size:20px !important}
/* === おすすめの理由: 控えめなタグ表示 === */
.whym{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;padding:10px 2px 12px !important;margin-bottom:4px !important;border-bottom:1px solid #ece9e2}
.whym span{flex:0 0 auto;font-size:11px;letter-spacing:.14em;color:#8a7a52;margin-right:4px}
.whym ul{display:contents !important}
.whym li{display:inline-flex !important;gap:6px;align-items:baseline;padding:3px 10px !important;margin:0 !important;background:#f7f5ee;border:1px solid #e6dfcc;border-radius:999px;font-size:12px;color:#4a5556;line-height:1.5}
.whym li b{font-weight:500;color:#6a8a5c;font-size:11px}.whym li.none{background:transparent;border-color:transparent;color:#8a9394;padding-left:0 !important}
.tools .f-none{display:none;flex:1 0 100%;font-size:13px;color:#8a7a52}.tools .f-none.on{display:block}

@stage@
@media(max-width:900px){.regions .region{grid-template-columns:1fr}.region .cover{min-height:130px;padding:16px 20px}.region .rank{font-size:40px}.spots{padding:6px 16px 10px}}
@media(max-width:700px){@mobile@}
</style>"""
CSS = CSS[:-len("</style>")] + open(os.path.join(BASE, "extra.css"), encoding="utf-8").read() + "</style>"
MOBILE = ("#topbar{padding:12px 16px !important;flex-wrap:wrap !important;gap:8px !important}.brand{font-size:14px;letter-spacing:.16em}.brand i{width:14px;margin:0 6px}"
          "#topbar .btns{flex:1 1 100% !important;width:100% !important;flex-wrap:nowrap !important}#topbar .btns>*{flex:1 1 0 !important;min-width:0 !important}"
          "#switch,#view{font-size:11px;padding:7px 8px !important}#hero{height:360px}#hero .txt{left:24px;bottom:36px;right:16px}#main{flex-direction:column !important;padding:16px !important}"
          ".regions .region{grid-template-columns:1fr}.region .cover{min-height:130px}.spot{flex-wrap:wrap}.region .name{font-size:24px}.region .pct{font-size:28px}")
FRAME = ".gradio-container{max-width:430px !important;margin:0 auto !important;box-shadow:0 0 0 1px @line@,0 10px 40px rgba(0,0,0,.18)}body{background:#dfe2e0 !important}"

_TRANS = ".gradio-container{background:transparent !important;position:relative;z-index:1}body,.app,.main{background:transparent !important}"
_PAD = ".gradio-container{padding-top:var(--hh,60px) !important}"
_TNR = '"Times New Roman",Times,"Cormorant Garamond","Shippori Mincho","Noto Serif TC","Hiragino Mincho ProN","Yu Mincho",serif'
STAGE = {"result": _TRANS + _PAD, "list": _TRANS + _PAD, "hotel": _TRANS + _PAD,
  # ② 条件設定: 全体を1つの枠で囲み、「T」の字で区切る（上=検索 / 左下=条件 / 右下=地図）
  "cond": _TRANS + _PAD + "#hsearch{display:none !important}"
     "#frame{width:min(1340px,94vw);margin:clamp(14px,2.6vh,30px) auto 40px !important;gap:0 !important;padding:0 !important;background:rgba(255,255,255,.94);border:1px solid @gold@;box-shadow:0 0 0 6px rgba(255,255,255,.2),0 0 0 7px rgba(199,161,90,.55),0 36px 90px rgba(0,0,0,.3)}"
     "#tbar{gap:12px !important;align-items:center !important;padding:20px clamp(20px,3vw,48px) !important;border:0 !important;border-bottom:1px solid @gold@ !important;background:transparent !important;border-radius:0 !important;position:relative}"
     "#tbar::before{content:'';position:absolute;left:clamp(20px,3vw,48px);top:-1px;width:56px;height:3px;background:@gold@}"
     "#tbar textarea,#tbar input{border:0 !important;border-bottom:1px solid @ink@ !important;border-radius:0 !important;background:transparent !important;box-shadow:none !important;font-family:@serif@ !important;font-size:17px !important;letter-spacing:.06em;padding:10px 4px !important}"
     "#tbar>*{background:transparent !important;border:0 !important;box-shadow:none !important;padding:0 !important}"
     "#main{gap:0 !important;padding:0 !important;align-items:stretch !important;flex-direction:column !important}"
     "#formcol{flex:0 0 auto !important;width:100% !important;max-width:none !important;padding:30px clamp(20px,3vw,48px) 34px !important;border:0 !important;border-bottom:1px solid @gold@ !important;border-radius:0 !important;background:transparent !important;box-shadow:none !important;position:relative}"
     "#formcol::before{content:'';position:absolute;left:50%;bottom:-6px;width:11px;height:11px;background:@gold@;transform:translateX(-50%) rotate(45deg);z-index:2}"
     "#formcol .form,#formcol .block{background:transparent !important;border-color:transparent !important;box-shadow:none !important}"
     ".chead{background:transparent !important;border:0 !important;padding:0 0 10px !important}"
     "#rescol{flex:0 0 auto !important;width:100% !important;max-width:none !important;padding:30px clamp(20px,3vw,48px) 34px !important;background:transparent !important;border:0 !important}"
     "#rescol .mapcard{background:transparent;border:0;padding:0}#rescol .block{background:transparent !important;border:0 !important;box-shadow:none !important}",
  # ① 国の選択: ボタンは画面に固定。タイトルはボタンの上に配置（重ならない）
  "landing": _TRANS + "body{overflow:hidden !important}#landing{position:fixed !important;inset:0;z-index:5;display:flex !important;gap:0 !important;align-items:center !important;justify-content:space-around !important;padding:0 !important;background:transparent !important;border:0 !important}#landing>*{flex:0 0 min(420px,42%) !important;width:auto !important}"
     "#pick-tw,#pick-jp{border:1px solid @gold@ !important;border-radius:2px !important;color:#fff !important;font-size:clamp(15px,1.4vw,19px) !important;letter-spacing:.14em;line-height:1.7;white-space:pre-line !important;padding:22px 20px !important;min-height:86px;box-shadow:0 10px 30px rgba(0,0,0,.25) !important}"
     "#pick-tw{background:#0b1c1d !important}#pick-jp{background:#12141f !important}#pick-tw:hover,#pick-jp:hover,#pick-tw:focus-visible,#pick-jp:focus-visible{background:@gold@ !important;color:#0b1c1d !important}"}
MOBILE2 = (".gradio-container{--hh:var(--tb,100px)}"
           ".bgfx .half{width:100% !important;height:50% !important;left:0 !important;right:auto !important;top:auto !important;bottom:auto !important}.bgfx .half.l{top:0 !important}.bgfx .half.r{top:50% !important}"
           ".bgfx .div{left:8% !important;right:8% !important;top:50% !important;bottom:auto !important;width:auto !important;height:1px !important}.bgfx .ttl{bottom:calc(50% + 66px) !important}"
           "#landing{flex-direction:column !important}#landing>*{flex:0 0 auto !important;width:min(330px,82%) !important}#pick-tw,#pick-jp{padding:16px 12px !important;min-height:70px}"
           "#topbar{height:auto !important;flex-wrap:wrap !important;padding:8px 12px !important;gap:6px 8px !important}#topbar>#home{order:1}#topbar>#menuhtml{order:2}#topbar>#hsearch{order:3;flex:1 1 100% !important;max-width:none !important;margin-left:0}#home,details.menu summary{font-size:12px !important;padding:8px 12px !important}.mlist{min-width:min(300px,86vw)}"
           "#main{flex-direction:column !important}#formcol,#rescol{max-width:none !important;flex:1 1 auto !important;width:100% !important}#formcol{border-right:0 !important;border-bottom:1px solid @gold@ !important}#formcol::before{display:none}"
           ".cat .spots,.spots{padding:4px 14px 8px}.pgcover{padding:18px}.hgrid{grid-template-columns:1fr}")
MOBILE3 = "html:has(#navmark[data-stage=landing]) gradio-app{background:transparent !important}.cchips{grid-template-columns:repeat(2,minmax(0,1fr)) !important;gap:10px !important;padding:16px 12px 6px !important}.cchip .cn b{font-size:12.5px !important}.cchip .cn{padding:8px 8px !important}.cpanels{padding:6px 12px 24px !important}.csort{grid-template-columns:repeat(2,1fr) !important;justify-content:stretch !important}.cgrid{grid-template-columns:1fr !important}#formcol,#rescol{padding-left:12px !important;padding-right:12px !important}#formcol .numhead,#rescol .numhead{margin:-30px -12px 18px !important}.numhead{padding:14px 14px 12px !important}.numhead b{width:34px !important;height:34px !important;font-size:17px !important}.numhead h3{font-size:16px !important;letter-spacing:.08em !important}.numhead p{font-size:12px !important}.fsech{flex-wrap:nowrap !important}.fsech small{display:none !important}.fsech span{font-size:15px !important;white-space:normal !important}#tbar{padding:16px 12px 18px !important}#tbar textarea,#tbar input{font-size:15px !important;padding:0 12px !important}#pbtn,#pbtn button,button#pbtn{padding:0 12px !important;min-width:64px}#rescol .mapcard{max-width:100% !important}html:has(#navmark[data-stage=landing]),body:has(#navmark[data-stage=landing]){background:#0b1c1d !important}.hlang{gap:4px !important;margin-right:6px !important}.hlang a,.hlang a:visited{padding:9px 11px !important;font-size:14px !important;min-width:40px !important}.lglabel{font-size:11.5px !important;margin-right:4px !important;letter-spacing:.04em !important}details.menu summary{padding:9px 12px !important;font-size:13px !important}body:has(#navmark[data-stage=landing]) #topbar{display:flex !important}body:has(#navmark[data-stage=landing]) #topbar>#home,body:has(#navmark[data-stage=landing]) #topbar>#hsearch{display:none !important}body:has(#navmark[data-stage=landing]) .landbrand,body:has(#navmark[data-stage=landing]) .landlang{display:none !important}body:has(#navmark[data-stage=landing]) .bgfx:has(.half){top:var(--tb,112px) !important;bottom:auto !important;height:292px !important}body:has(#navmark[data-stage=landing]) .bgfx .half{width:100% !important;height:146px !important}body:has(#navmark[data-stage=landing]) .bgfx .half.l{top:0 !important}body:has(#navmark[data-stage=landing]) .bgfx .half.r{top:146px !important}body:has(#navmark[data-stage=landing]) .bgfx .div{top:146px !important}body:has(#navmark[data-stage=landing]) .bgfx .ttl{top:12px !important;bottom:auto !important}body:has(#navmark[data-stage=landing]) .bgfx .ttl b{font-size:26px !important;letter-spacing:.2em !important}body:has(#navmark[data-stage=landing]) .bgfx .ttl span{font-size:11.5px !important;margin-top:4px !important}body:has(#navmark[data-stage=landing]) #landing{position:fixed !important;inset:auto !important;top:var(--tb,112px) !important;left:50% !important;width:min(100vw,430px) !important;height:292px !important;transform:translateX(-50%);display:grid !important;grid-template-rows:146px 146px;justify-items:center !important;align-items:end !important;align-content:start !important;justify-content:center !important;padding:0 !important}body:has(#navmark[data-stage=landing]) #landing>*{width:min(300px,80%) !important;margin:0 0 14px !important}body:has(#navmark[data-stage=landing]) #pick-tw,body:has(#navmark[data-stage=landing]) #pick-jp{min-height:44px !important;padding:10px 8px !important;font-size:14px !important;letter-spacing:.04em !important;white-space:nowrap !important}body:has(#navmark[data-stage=landing]) .howto{position:fixed !important;top:calc(var(--tb,112px) + 304px) !important;bottom:auto !important;left:50% !important;transform:translateX(-50%) !important;width:calc(min(100vw,430px) - 24px) !important;margin:0 !important;max-height:calc(100vh - var(--tb,112px) - 316px) !important;overflow:auto !important;padding:10px 14px !important}body:has(#navmark[data-stage=landing]) .howto ul,body:has(#navmark[data-stage=landing]) .howto ol{font-size:12px !important;line-height:1.55 !important}body:has(#navmark[data-stage=landing]) .hwg{gap:6px !important;margin-top:6px !important}body:has(#navmark[data-stage=landing]) .howto h4{margin-bottom:2px !important}body:has(#navmark[data-stage=result]) #main{display:flex !important;flex-direction:column !important}body:has(#navmark[data-stage=result]) #rescol{order:1 !important}body:has(#navmark[data-stage=result]) #formcol{order:2 !important}"
MOBILE3 += (   # スマホのエリアページ: 枠を画面の端近くまで広げ、単語の途中で改行しない大きさにする
 "#pagecol{padding-left:6px !important;padding-right:6px !important}#pagecol .html-container{padding-left:0 !important;padding-right:0 !important}"
 ".pg{padding-left:2px !important;padding-right:2px !important;margin-left:0 !important;margin-right:0 !important;max-width:none !important;box-sizing:border-box !important}"
 ".pg .pgcover,.pg .guidebox,.pg section.cat,.pg .hotelpg{margin-left:0 !important;margin-right:0 !important;width:auto !important;max-width:none !important;box-sizing:border-box !important}"
 ".pg .pgcover{margin:4px 3px 22px !important;outline-offset:3px !important;padding:22px 20px !important;min-height:200px !important}"
 ".pg .guidebox{padding-left:14px !important;padding-right:14px !important}"
 ".pg,.pg *{word-break:auto-phrase;line-break:strict}.pg h2,.pg h3,.pg p,.pg .sd{text-wrap:pretty}"
 ".pg .guidebox h3{font-size:15px !important;letter-spacing:.1em !important}"
 ".pg .catbox h3.big{font-size:17.5px !important;letter-spacing:.06em !important;white-space:nowrap}"
 ".pg .ic3 strong,.pg .ic3 .nm{font-size:15px !important}"
 ".pg .season li,.pg .season p,.pg .wx small,.pg .guidebox .sn{font-size:12.5px !important}"
 ".pg .ahbox .ahrow{padding:14px !important}.pg .ahbox .ahrow p{font-size:13px !important;flex-basis:100% !important}"
 ".pg .ahbox .areahotel{font-size:14px !important;letter-spacing:.06em !important;padding:0 10px !important;white-space:nowrap}"
 ".pg section.cat>h3{font-size:18px !important;letter-spacing:.06em !important;padding-left:14px !important;padding-right:14px !important;gap:10px !important;white-space:nowrap}"
 ".pg section.cat>h3 em{white-space:nowrap !important;font-size:12px !important;padding:3px 9px !important;flex:none !important}"
 ".pg section.cat .spots{padding-left:10px !important;padding-right:10px !important}"
 ".pg .spot .nm>b,.pg .spot .nm>strong,.pg .spot .nm>a{font-size:15px !important}.pg .spot .sd{font-size:12.5px !important;letter-spacing:0 !important;line-height:1.7 !important}"
 ".pg .spot .acts a,.pg .spot .acts button{font-size:12.5px !important;letter-spacing:.02em !important;white-space:nowrap !important;padding-left:2px !important;padding-right:2px !important}"
 ".cmpc dt{white-space:nowrap;font-size:10px !important;letter-spacing:0 !important}.cmpc dd{font-size:11.5px !important}.cmpc{padding:10px 4px 8px !important}"
)
MOBILE3 += (   # スマホ: 準備ガイド・レンタカー・ホテル・検索結果（2ページ目と同じ枠のページ）
 ".pg.lux{padding:0 0 24px !important}.luxframe{width:100% !important;margin:10px 0 20px !important;box-sizing:border-box}"
 ".lux .p2country span{font-size:clamp(20px,6.6vw,28px) !important;letter-spacing:.12em !important;padding-left:.12em !important;white-space:nowrap}.lux .p2country{gap:10px !important}.lux .p2ways li{width:100% !important}.lux .p2ways a.p2way{width:100% !important}.lux .luxt{background:linear-gradient(180deg,rgba(255,255,255,.55),rgba(255,255,255,.84) 22%,rgba(255,255,255,.84) 78%,rgba(255,255,255,.55)) !important;padding-bottom:26px !important}.lux .p2title h1{font-size:23px !important;letter-spacing:.08em !important}"
 ".lux .p2ways{flex-direction:column !important;align-items:stretch !important;gap:8px !important;padding:0 10px !important}.lux .p2ways a.p2way{height:auto !important;min-height:42px;padding:8px 14px !important;font-size:13px !important;letter-spacing:.04em !important;text-align:left}"
 ".luxbody{padding:16px 12px 22px !important}.lux .numhead .nhx{font-size:11px !important;padding:3px 9px !important}"
 ".infog{grid-template-columns:1fr !important}.ckgrid{grid-template-columns:1fr !important}.evgrid{grid-template-columns:1fr !important}"
 ".lux .hgrid{grid-template-columns:1fr !important;gap:9px !important}.lux .hitgrid{grid-template-columns:1fr !important}.hitx{min-height:170px !important}"
 ".lux .spots{padding:0 !important}.luxnote{margin:14px 14px 18px !important}"
)
FRAME2 = "#frame{width:100% !important;margin:0 0 24px !important}.hwg{grid-template-columns:1fr !important}.ic3g{grid-template-columns:1fr !important}.regions .region{grid-template-columns:1fr !important}.bgfx{left:50% !important;right:auto !important;width:min(430px,100vw) !important;transform:translateX(-50%)}#topbar{left:50% !important;right:auto !important;width:min(430px,100vw) !important;transform:translateX(-50%)}"

def kf(n):                          # n枚を SLIDE_SEC 秒ごとにクロスフェード
    T_, f = SLIDE_SEC * n, 1.2
    return (f"@keyframes hz{n}{{0%{{opacity:0}}{f/T_*100:.3f}%{{opacity:1}}{(SLIDE_SEC+f)/T_*100:.3f}%{{opacity:1}}"
            f"{(SLIDE_SEC+2*f)/T_*100:.3f}%{{opacity:0}}100%{{opacity:0}}}}")

FOCUS = json.load(open(os.path.join(BASE, "data", "focus.json"), encoding="utf-8")) if os.path.exists(os.path.join(BASE, "data", "focus.json")) else {}
def bgpos(reg):                       # エリア写真の「主役」の位置（%）。カードや背景でその部分が見えるように表示位置を指定
    fx, fy = FOCUS.get(reg, (50, 50)); return f"background-position:{fx}% {fy}%;"
FONTS = {"ja": dict(serif=TH["taiwan"]["serif"], sans=TH["taiwan"]["sans"]), "zh": dict(serif=TH["japan"]["serif"], sans=TH["japan"]["sans"]),
         "en": dict(serif="'Cormorant Garamond','Times New Roman',Times,'Shippori Mincho',serif", sans="'Noto Sans JP','Helvetica Neue',Arial,sans-serif")}

def whole_bg(u):                   # エリア写真を切らずに全体表示。余白は同じ写真をぼかして敷く
    return (f'<div class="slide blurfill" style="background-image:url(\'{u}\');opacity:1"></div>'
            f'<div class="slide whole" style="background-image:url(\'{u}\');opacity:1"></div>')

def layers(imgs, pos=""):
    n = len(imgs); anim = "" if n == 1 else f"animation:hz{n} {SLIDE_SEC * n}s infinite;"
    return "".join(f'<div class="slide"{(" data-bg=" + chr(34) + u + chr(34)) if k else ""} style="{("background-image:url(" + chr(39) + u + chr(39) + ");") if not k else ""}{pos}{anim}animation-delay:{k * SLIDE_SEC}s;{"opacity:1;" if n == 1 else ""}"></div>' for k, u in enumerate(imgs))

def bg_images(m):                   # images/bg/bg_<market>_<番号>.jpg（軽量版）。なければheroを流用
    fs = glob.glob(os.path.join(BASE, "images", "bg", f"bg_{m}_*"))
    return [asset(os.path.relpath(f, BASE)) for f in sorted(fs, key=lambda f: int(re.search(r"_(\d+)\.", f).group(1)))] or hero_images(m)

def chead_html(m, lang): t = TX(m, lang); return f'<div class="chead"><span class="orn"><i></i><u></u><i></i></span><h2>{t["cond"]}</h2><p>{t["condsub"]}</p></div>'
def empty_html(m, lang): return f'<div class="res-empty">{TX(m, lang)["empty"]}</div>'

MOBILE3 += (   # スマホのヘッダーを低く(11/16 夜): サイト名・戻る・言語・PC表示・メニューを1行に、検索欄は2行目に細く
    "#topbar{padding:6px 6px !important;gap:6px 5px !important}#topbar>#brand{order:0 !important;flex:0 0 auto !important}#topbar>#home{order:1 !important}"
    "#topbar>#menuhtml{order:2 !important;margin-left:auto !important}#topbar>#hsearch{order:3 !important;flex:1 1 100% !important;max-width:none !important;margin-left:0 !important}"
    ".brandlink b{font-size:17px !important;letter-spacing:.02em !important}.brandlink i{display:none !important}"
    "#home,button#home{font-size:11.5px !important;padding:6px 6px !important;min-height:0 !important;min-width:0 !important;line-height:1.2 !important;white-space:nowrap !important}"
    ".lglabel{display:none !important}.hlang{gap:3px !important;margin-right:5px !important}.hlang a,.hlang a:visited{padding:6px 5px !important;font-size:12px !important;min-width:26px !important;line-height:1.2 !important}#menuhtml .hm{flex-wrap:nowrap !important}#menuhtml .hm{padding:0 !important;margin:0 !important;gap:0 !important}#menuhtml .hm a.viewbtn svg{display:none !important}.brandlink{padding:0 !important;margin:0 !important}"
    "#menuhtml .hm a.viewbtn,#menuhtml .hm a.viewbtn:visited{padding:6px 7px !important;font-size:11.5px !important;margin-right:5px !important;gap:4px !important;letter-spacing:.02em !important;line-height:1.2 !important}#menuhtml .hm a.viewbtn svg{width:14px !important;height:14px !important;flex-basis:14px !important}"
    "details.menu summary{padding:6px 8px !important;font-size:11.5px !important;letter-spacing:.04em !important;line-height:1.2 !important}details.menu summary::before{width:11px !important;margin-right:5px !important}"
    "#hsearch textarea,#hsearch input{min-height:34px !important;height:34px !important;font-size:13px !important;padding:0 10px !important}#hbtn,button#hbtn{min-height:34px !important;height:34px !important;padding:0 12px !important;font-size:12px !important}")
MOBILE3 += (   # スマホ: 各ページ上部の余白を詰める(11/16 夕)。背景・目印だけの部品と空の入力枠が、高さ0でも並びの間隔(16px×数個)を取っていた
    ".gradio-container .block:has(#navmark:not([data-stage=result])){position:absolute !important;height:0 !important;min-height:0 !important;padding:0 !important;margin:0 !important}"
    ".gradio-container .block:has(#navmark:not([data-stage=result]))>.html-container{padding:0 !important}"
    ".gradio-container .form:not(:has(>:not(.hidden-bridge))){position:absolute !important}"
    "#pagecol{padding-top:4px !important}.pg{padding-top:8px !important}.pg.lux{padding-top:0 !important}.luxframe{margin-top:8px !important}"
    "#p2t{margin-top:0 !important}#p2t .p2title,.lux .p2title.luxt{padding-top:20px !important}"
)
TOKENS = ("ink", "deep", "gold", "bg", "line", "serif", "sans")
def _tokens(m, landing, lang):          # 国の配色・言語のフォント。CSS変数(:root)として小さな部品(cssS)で送る
    tk = dict(TH["taiwan" if landing else m]); tk.update(FONTS[lang]); return ":root{" + "".join(f"--{k}:{tk[k]};" for k in TOKENS) + "}"
def _vars(css):
    for k in TOKENS: css = css.replace(f"@{k}@", f"var(--{k})")
    return css
MOBILE3 += (   # スマホ: 交通手段を探す（11/17）
 ".trnav{flex-direction:column !important;align-items:stretch !important;padding:0 10px !important;gap:10px !important;width:100% !important;box-sizing:border-box}.trnav a.trnav-b{max-width:none !important;flex:0 0 auto !important;padding:11px 14px 11px 11px !important}.trnav-i{width:40px !important;height:40px !important}.trnav-t b{font-size:15px !important}"
 ".trgrid{grid-template-columns:1fr !important;gap:12px !important}.trc{padding:16px 15px 14px !important}.trnm{font-size:17px !important}.trpg .trtip{padding:10px 12px !important;font-size:12.5px !important}.tracts a.trb{height:40px !important}"
)
_MOBILE_ALL = MOBILE + MOBILE2 + MOBILE3
def _css_parts():
    i = CSS.index("@stage@"); a_, b_ = CSS[:i] + "</style>", "<style>" + CSS[i + len("@stage@"):]
    a_ = a_.replace("<style>", "<style>" + _tokens(START, True, "ja"), 1)       # 初期値（cssS が上書きする）
    return _vars(a_), _vars(b_.replace("@mobile@", _MOBILE_ALL))
CSS_A, CSS_B = _css_parts()
CSS_M = "<style>" + _vars(_MOBILE_ALL + FRAME + FRAME2) + "</style>"          # 「スマホ表示」を選んだとき（PCの画面幅でも430px幅で表示）
def theme_css(m=None, v=None, landing=None, lang=None):
    """CSS本体。国・言語・表示モードによらず同じ内容（配色とフォントは CSS変数）なので、最初に1回送るだけで済む。前半 / 後半 に分けて返す。間に画面別CSS(stage_css)が入る"""
    return CSS_A, CSS_B
def mobile_css(v): return CSS_M if v == "mobile" else ""
@functools.lru_cache(maxsize=64)
def stage_css(m, st, lang):
    return "<style>" + _tokens(m, st == "landing", lang) + _vars(STAGE[st]) + "</style>"
@functools.lru_cache(maxsize=256)
def theme_html(m, v="pc", st="result", depth=1, bgr=None, lang="ja"):
    """画面(st)ごとの背景・履歴用マーカー(#navmark)を返す。CSSは theme_css / stage_css が別の部品として返す"""
    css = ""
    mark = f'<i id="navmark" data-depth="{depth}" data-stage="{st}" hidden></i>'      # ブラウザの「戻る」と同期するための目印
    t = TX(m, lang)
    if st == "landing":      # ① 国の選択: 左=台湾 / 右=日本 の背景スライドショー（薄いベール付き）
        tw, jp = bg_images("taiwan"), bg_images("japan")
        kfs = "".join(kf(n) for n in {len(tw), len(jp)} if n > 1)
        return css + f"<style>{kfs}</style>" + mark + (
            f'<div class="bgfx"><div class="half l">{layers(tw)}<div class="ttl"><b>TAIWAN</b><span>{TX("taiwan", lang)["title"]}</span></div></div>'
            f'<div class="half r">{layers(jp)}<div class="ttl"><b>JAPAN</b><span>{TX("japan", lang)["title"]}</span></div></div>'
            f'<i class="div"></i><div class="veil"></div></div>')
    if st in ("cond", "list", "hotel"):   # ② 条件設定 / ④⑤ 一覧・ホテル: 薄くした写真を背景に（④⑤は該当エリアの写真）
        photo = region_photo(bgr) if bgr else None
        imgs = [photo] if photo else bg_images(m); kfs = kf(len(imgs)) if len(imgs) > 1 else ""
        title = ""
        return css + f"<style>{kfs}</style>" + mark + f'<div class="bgfx">{layers(imgs, bgpos(bgr) if photo else '')}<div class="veil"></div></div>' 
    imgs = hero_images(m); n = len(imgs)     # ③ 結果: トップ写真（SLIDE_SEC秒ごと）
    if n:
        css += f"<style>{kf(n) if n > 1 else ''}@media(prefers-reduced-motion:reduce){{.slide{{animation:none !important}}.slide:first-child{{opacity:1 !important}}}}</style>"
        slides, bg = layers(imgs), ""
        css += f'<div class="bgfx rbg">{layers([u.replace("/images/hero/", "/images/herob/") for u in imgs])}<div class="veil"></div></div>'      # 写真の下の余白は、同じ写真をぼかして画面いっぱいに拡張
    else:
        slides, bg = "", ""
    return css + mark + (f'<div id="hero"{bg}>{slides}<div class="shade"></div>'
                  f'<div class="txt"><h1>{t["title"]}</h1><i class="rule"></i><p>{t["desc"].rstrip("。").replace("。", "。<br>") + ("。" if t["desc"].endswith("。") else "")}</p></div></div>')


# ---------------- 検索用: 表記ゆれの正規化（繁體・新字体・簡体を同一視して比較） ----------------
VAR = str.maketrans({"縣": "県", "臺": "台", "灣": "湾", "國": "国", "廣": "広", "關": "関", "繩": "縄", "兒": "児", "溫": "温", "澤": "沢", "邊": "辺", "舊": "旧", "號": "号", "驛": "駅", "學": "学", "會": "会", "歷": "歴",
                     "东": "東", "县": "県", "广": "広", "关": "関", "门": "門", "龙": "竜", "龍": "竜"})
try: SPOT_EN = json.load(open(os.path.join(BASE, "data", "spot_en.json"), encoding="utf-8"))
except Exception: SPOT_EN = {}
def en_of(name, lang="en"):
    """英語表示のときだけ付ける英語名。原名と同じ・空のときは付けない"""
    if lang != "en": return ""
    e = SPOT_EN.get(str(name), "").strip()
    return e if e and e.lower() != str(name).strip().lower() else ""
def en_tag(name, lang): e = en_of(name, lang); return f' <span class="en">{html.escape(e)}</span>' if e else ""
def norm(s): return unicodedata.normalize("NFKC", str(s)).casefold().translate(VAR)
CATN = {c[0]: [norm(c[2]), norm(c[3]), norm(c[4])] for c in CATS}
CN = {"taiwan": dict(ja="台湾", zh="台灣", en="Taiwan"), "japan": dict(ja="日本", zh="日本", en="Japan")}
CWORDS = {m: {norm(x) for x in ws} for m, ws in {"taiwan": ("台湾", "台灣", "臺灣", "taiwan"), "japan": ("日本", "japan", "nippon")}.items()}
IDX = []                                              # サイト内の「ページ」= 各エリアの一覧ページ。エリア名・スポット名・分類名を索引化
for _m, _d in D.items():
    _sp = _d["spots"].drop_duplicates("spot")
    for _reg, _g in _sp.groupby("region"):
        IDX.append(dict(m=_m, reg=_reg, rn=[norm(rname(_reg, l)) for l in ("ja", "zh", "en")] + [norm(_reg)], cats=sorted(set(_g["cat"])), spots=[(s, norm(s + " " + SPOT_EN.get(s, ""))) for s in _g["spot"]]))

def search_all(q, cur, lang):
    nq = norm(q).strip(); out = []
    if not nq: return out
    for e in IDX:
        rhit = any(nq in x for x in e["rn"]) or nq in CWORDS[e["m"]]
        shits = [s for s, ns in e["spots"] if nq in ns]; chits = [c for c in e["cats"] if nq in CATN[c][{"ja": 0, "zh": 1, "en": 2}[lang]]]      # 分類名は表示中の言語のものだけ照合
        if rhit or shits or chits: out.append((e, rhit, shits, chits))
    out.sort(key=lambda x: (x[0]["m"] != cur, not x[1], -len(x[2]), x[0]["reg"])); return out

# ---------------- 部品: クリック橋渡し(JS) / スポット行 ----------------
# HTML内のクリックを、非表示テキストボックス(#bridge)経由でPython側へ渡す
def jsgo(*parts): return html.escape("tjNav(%s);return false;" % json.dumps("\t".join(parts), ensure_ascii=False), quote=True)      # tjNav はHEADで定義(各ボタンに長いJSを埋め込まない)
STOP = 'onclick="event.stopPropagation()"'
def catname(lang, key): c = next(c for c in CATS if c[0] == key); return {"ja": c[2], "zh": c[3], "en": c[4]}[lang]

# ---------------- 部品: クリック橋渡し(JS) / スポット行 ----------------
FEAT = dict(food=("グルメ", "美食", "food"), nature=("自然景観", "自然風光", "scenery"), history=("歴史・文化", "歷史文化", "history and culture"), city=("都市の雰囲気", "都會氛圍", "urban atmosphere"),
            shopping=("ショッピング", "購物", "shopping"), nightlife=("夜の楽しみ", "夜間娛樂", "nightlife"), relaxation=("癒やし", "放鬆療癒", "relaxation"), photography=("写真映え", "拍照景點", "photo spots"))
SEA_RESUB = {"lake", "river", "gorge", "mount", "forest", "fall", "wet", "garden", "flower", "farm", "misc"}
def spot_desc(m, lang, r, reg):
    """スポットの紹介文。個別の文(data/desc.json)があればそれを、なければ種類別の文を使う(desc.py)"""
    c = PLACE.get(m, {}).get(r["spot"])
    place = rname(reg, lang) if lang == "en" else place_term(m, rname(reg, lang) if not c else reg, r["spot"])
    sub = "beach" if r["cat"] == "nature" and r.get("ngen") == "sea" and subtype(r["spot"], r["cat"]) in SEA_RESUB else None      # 「海」に入ったスポットに湖・川などの文を使わない（例: 後壁湖）
    x = extra_desc.extra(r["spot"], r["cat"], r, lang).strip(); body = describe(r["spot"], r["cat"], place, lang, {k: r.get(k) for k in FEAT}, VARI.get((reg, r["spot"])), sub)
    return (x + "\n" + body) if x else body      # クラブ=音楽ジャンル / アクティビティ=できること
DUPNAME = {_m: set(_v[_v > 1].index) for _m, _v in ((_m, _d["spots"].drop_duplicates(["region", "spot"])["spot"].value_counts()) for _m, _d in D.items())}
VARI = {}      # (エリア, スポット) -> 文の番号。同じエリア・同じ種類のスポットに、文を順番に割り当てる
for _m, _d in D.items():
    _cnt = {}
    for _r in _d["spots"].drop_duplicates(["region", "spot"]).itertuples():
        _k = (_r.region, subtype(_r.spot, _r.cat)); VARI[(_r.region, _r.spot)] = _cnt.get(_k, 0); _cnt[_k] = _cnt.get(_k, 0) + 1

def sd_html(s):          # 紹介文は句点(。/ 英語は文末)ごとに改行する
    head, _, body = s.rpartition("\n")          # 1行目: ナイトクラブ=音楽ジャンル / アクティビティ=できること（extra_desc）
    s = html.escape(body); s = re.sub(r"。(?=.)", "。<br>", s); s = re.sub(r"(?<=[a-z\)])\. (?=[A-Z])", ".<br>", s)
    return (f'<b class="sdx">{html.escape(head)}</b>' if head else "") + s
def spot_row(m, lang, r, reg, show_reg=False, i=0, extra=""):
    t = TX(m, lang); q = quote_plus(f'{r["spot"]} {reg}'); u = str(r.get("official_url", "")).strip(); site = ""; has_off = 0
    if str(r.get("recommended_link_status", "")) == "verified_detail":            # 個別ページ確認済みのURLがあればそちらを優先
        ru = str(r.get("recommended_link_url", "")).strip()
        if ru.lower().startswith(("http://", "https://")): u = ru
    nv = r.get("new_within_1y_flag"); is_new = bool(pd.notna(nv) and int(nv) == 1)       # 最新（1年以内オープン）フラグ
    od = r.get("opened_date"); od = str(od) if pd.notna(od) else ""
    badge = f'<span class="newb" title="{html.escape(LBL[lang]["new_tip"] + (" " + od if od else ""), quote=True)}">New</span>' if is_new else ""
    if u.lower().startswith(("http://", "https://")):          # CSVのofficial_url（http/httpsのみ許可）
        off = r.get("official_url_type") in ("spot_official", "official_site")      # スポット専用の公式サイトか、エリアの観光公式か
        has_off = 1 if off else 0
        site = f'<a class="s-site {"off" if off else ""}" href="{html.escape(u, quote=True)}" target="_blank" rel="noopener noreferrer" {STOP}>{t["site" if off else "rsite"]}</a>'
    rg = f'<small class="rg">{html.escape(rname(reg, lang))}</small>' if show_reg else ""
    site = site or '<span class="ph" aria-hidden="true"></span>'      # 公式サイトが無い行も空きスロットを確保し、ホテルボタンの位置を固定する
    ea = lambda x: html.escape(x, quote=True)
    return (f'<div class="spot" data-off="{has_off}" data-new="{1 if is_new else 0}" data-g="{ea(str(r.get("ngen", "") or ""))}" data-nm="{ea((str(r["spot"]) + " " + en_of(r["spot"], lang)).lower())}" data-i="{i}"><div class="ic">{CATICON[r["cat"]]}</div><div class="nm">{badge}{html.escape(r["spot"])}{en_tag(r["spot"], lang)}{rg}{extra}<span class="sd">{sd_html(spot_desc(m, lang, r, reg))}</span></div><div class="acts">'
            f'<a class="s-map" href="https://www.google.com/maps/search/?api=1&query={q}" target="_blank" rel="noopener" {STOP}>{t["map"]}</a>'
            f'<a class="alt s-img" href="https://www.google.com/search?tbm=isch&q={q}" target="_blank" rel="noopener" {STOP}>{t["img"]}</a>{site}'
            f'</div>'
            f'<button type="button" class="star" data-reg="{ea(reg)}" data-sp="{ea(r["spot"])}" title="{ea(t["fav_add"])}" aria-label="{ea(t["fav_add"])}" onclick="event.stopPropagation();tjFav(this)">★</button></div>')

# ---------------- ベストシーズン / 比較 / 理由 / モデル説明 ----------------
MONTH_EN = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
def season_html(reg, lang, t):
    months, tags = SEASON.get(reg, ([], []))
    if not months: return ""
    now = datetime.date.today().month
    cells = "".join(f'<i class="{"on" if k in months else ""}{" now" if k == now else ""}" title="{MONTH_EN[k - 1] if lang == "en" else f"{k}月"}"><b>{MONTH_EN[k - 1] if lang == "en" else k}</b></i>' for k in range(1, 13))
    tg = "".join(f"<li>{TAGS[x][lang]}</li>" for x in tags)
    evs = events_for_region(reg, lang); ev = ""
    if evs:          # このエリアの行事: 時期 / 種類 / 行事 の表
        c_ = LBL[lang]["ev_cols"]; rn_ = html.escape(rname(reg, lang))
        trs = "".join(f'<tr><th scope="row">{html.escape(w)}</th><td class="tg">{guide.evtag_html(tg, lang)}</td><td><span class="evname">{html.escape(nm)}</span>{f"<small>{html.escape(dt)}</small>" if dt else ""}</td></tr>' for w, nm, dt, tg in evs)
        ev = (f'<div class="evtw"><h3 class="evh">{LBL[lang]["ev_region"].format(reg=rn_)}</h3><table class="evtbl"><thead><tr><th scope="col">{c_[0]}</th><th scope="col">{c_[1]}</th><th scope="col">{c_[2]}</th></tr></thead><tbody>{trs}</tbody></table></div>')
    return (f'<div class="season"><h3>{t["season_title"]}</h3><div class="mrow">{cells}</div>'
            f'<div class="sinfo"><p class="best"><span>{t["season_best"]}</span><b class="rng">{ranges(months, lang)}</b><em>{t["season_now"]}＝◎</em></p>{f"<ul>{tg}</ul>" if tg else ""}</div>{ev}<p class="sn">{t["season_note"]}</p></div>')

ICONIC = dict(ja=("{reg}といえば…", "エリアの知名度・象徴性が高い代表的な観光地です（データの代表性評価による）。"),
              zh=("說到{reg}…", "此地區知名度與象徵性高的代表性景點（依資料中的代表性評估）。"),
              en=("{reg} is known for…", "Well-known, representative sights of this region (based on the data's representativeness rating)."))
def iconic_html(m, reg, lang):
    d = D[m]["spots"]; g = d[(d.region == reg) & (d["iconic_region_flag"] == 1)].drop_duplicates("spot").sort_values("iconic_region_rank").head(3)
    if g.empty: return ""
    cards = "".join(f'<a class="ic3" href="https://www.google.com/search?tbm=isch&q={quote_plus(str(r["spot"]) + " " + reg)}" target="_blank" rel="noopener"><b>{i}</b><span class="n">{html.escape(str(r["spot"]))}{en_tag(r["spot"], lang)}</span><small>{CATICON[r["cat"]]}{catname(lang, r["cat"])}</small></a>' for i, (_, r) in enumerate(g.iterrows(), 1))
    return f'<div class="iconic"><h3>{ICONIC[lang][0].format(reg=html.escape(rname(reg, lang)))}</h3><div class="ic3g">{cards}</div><p class="sn">{ICONIC[lang][1]}</p></div>'

def region_stats(m, reg):
    s = D[m]["spots"]; s = s[s.region == reg].drop_duplicates("spot")
    return dict(n=len(s), off=int(s["official_url"].astype(str).str.lower().str.startswith(("http://", "https://")).sum()),
                cats=s["cat"].value_counts().to_dict(), sc={k: float(s[k].mean()) for k in CORE})

def compare_html(m, lang, regs, probs):
    """上位3エリアの比較(必要な項目だけ): 一致度 / スポット数 / ベストシーズン / 今月"""
    t = TX(m, lang); now = datetime.date.today().month
    cols = "".join(f'<div class="cmpc"><b>{html.escape(rname(r, lang))}</b><span class="p">{p:.0%}</span>'
                   f'<dl><dt>{t["cmp_spots"]}</dt><dd>{region_stats(m, r)["n"]}</dd><dt>{t["cmp_season"]}</dt><dd>{ranges(SEASON.get(r, ([], []))[0], lang) or "–"}</dd>'
                   f'<dt>{t["cmp_now"].format(m=now)}</dt><dd>{"◎" if now in SEASON.get(r, ([], []))[0] else "–"}</dd></dl></div>' for r, p in zip(regs, probs))
    return f'<div class="cmp2"><h3>{t["cmp_title"]}</h3><div class="cmpg">{cols}</div></div>'

INV = {v: k for k, v in KEYS.items()}
def note_html(t): return f'<div class="note">{t["note"]}</div>' if t["note"] else ""
def feat_text(f, row, t, lang, m="taiwan", c=None):
    if f == "trip_days": return t["why_days"].format(n=int(row[f]))
    if f == "budget_per_day":
        c = c or FXB[m]; return t["why_budget"].format(n=fmtc(conv(float(np.expm1(row[f])), FXB[m], c), c))
    if f == "party_type": return t["why_party"].format(p={v: p[lang] for v, p in PARTY}[row[f]])
    if f == "first_visit": return t["why_first"] if int(row[f]) else t["why_repeat"]
    k = f[:-9] if f.endswith("_interest") else INV[f]
    return f'{t["sl"][k]} {int(row[f])}/5'

def model_note(m, lang):
    t, d = TX(m, lang), D[m]; ev = EVAL.get(m, {})
    algo = type(d["model"].named_steps["clf"]).__name__ if hasattr(d["model"], "named_steps") else type(d["model"]).__name__
    body = [t["model1"].format(algo=algo), t["model2"]]
    if ev: body.append(t["model3"].format(t1=f'{ev["t1"]:.1%}', r1=f'{1 / ev["ncls"]:.1%}', t3=f'{ev["t3"]:.1%}', t5=f'{ev["t5"]:.1%}'))
    return f'<details class="modelnote"><summary>{t["model_title"]}</summary>{"".join(f"<p>{x}</p>" for x in body)}</details>'

# ---------------- ③ 結果（エリアランキング Top5） ----------------
FIRST_W = 1.2          # 「初めて」のときの定番度の効き具合（大きいほど定番エリアを強く優先）
FIRST_INFO = dict(ja="「初めて」を選ぶと、定番スポットの多いエリアが上位に出やすくなります。「2回目以降」では定番の優先をせず、好みや条件に合うエリアを中心に表示します。",
                  zh="選「第一次」時，定番景點多的地區會排名較前；選「去過（再訪）」則不優先定番，以符合喜好與條件的地區為主。",
                  en="Choosing “first trip” ranks regions with many must-see sights higher. “I've been before” skips that boost and favors regions that fit your tastes and conditions.")
def _pop(m):                       # エリアの定番度(0〜1): 観光価値の高い上位スポットの平均 + 「このエリアといえば」該当数 をエリア間で順位化
    sp = D[m]["spots"].drop_duplicates("spot"); g = sp.groupby("region")
    top = g["tourism_value_score"].apply(lambda x: x.fillna(0).nlargest(5).mean()); ic = g["iconic_region_flag"].apply(lambda x: (x == 1).sum())
    return ((top.rank(pct=True) + ic.rank(pct=True)) / 2).rank(pct=True).to_dict()
POP = {m: _pop(m) for m in D}
def recommend(m, lang, days, budget, party, first, *scores, v="pc", cur="USD"):
    first = first in (True, "first", 1); d, t = D[m], TX(m, lang); cu = cur_of(lang, cur)
    vals = dict(zip(ALL, scores))
    row = {"trip_days": days, "budget_per_day": np.log1p(conv(budget or 0, cu, FXB[m])), "party_type": party, "first_visit": int(first in (True, "first", 1))}
    for k, val in vals.items(): row[KEYS.get(k, f"{k}_interest")] = val
    feats = d["feats"]; X = pd.DataFrame([row])[feats]; classes = list(d["model"].classes_)
    pv = d["model"].predict_proba(X)[0]
    if first: pv = pv * (1 + FIRST_W * np.array([POP[m].get(c, 0.0) for c in classes])); pv = pv / pv.sum()      # 初めての旅行: 定番スポットの多いエリアを優先
    p = pd.Series(pv, index=classes).sort_values(ascending=False, kind="stable")
    alt = []                                   # 各条件を「平均的な値」に置き換えた入力（寄与度の計算用）
    for f in feats: r2 = dict(row); r2[f] = d["base"][f]; alt.append(r2)
    delta = pv[None, :] - d["model"].predict_proba(pd.DataFrame(alt)[feats])      # 行=条件, 列=エリア: 一致度がどれだけ下がるか
    pref = np.array([vals[k] for k in SPOT_COLS])
    out = [f'<div class="hd">{t["res"]}</div><div class="regions">']
    for i, (reg, pr) in enumerate(p.head(5).items(), 1):
        allr = d["spots"][d["spots"].region == reg].drop_duplicates("spot")
        s = allr.copy(); s["match"] = s[SPOT_COLS].to_numpy() @ pref + s["tourism_value_score"].fillna(0).to_numpy() / 100
        rows = "".join(spot_row(m, lang, r, reg, i=j) for j, (_, r) in enumerate(s.sort_values("match", ascending=False, kind="stable").head(5).iterrows()))
        c = delta[:, classes.index(reg)]; top = [j for j in np.argsort(-c, kind="stable")[:3] if c[j] > 0.002]
        why = "".join(f'<li>{html.escape(feat_text(feats[j], row, t, lang, m, cu))}<b>+{c[j] * 100:.1f}pt</b></li>' for j in top) or f'<li class="none">{t["why_none"]}</li>'
        bg = region_photo(reg); cover = f"background-image:url('{bg}');{bgpos(reg)}" if bg else f"background-image:url('{cover_svg(m, i)}')"
        out.append(f'<div class="rw"><div class="region" role="link" tabindex="0" onclick="{jsgo("region", reg)}"><div class="cover" style="{cover}"><div class="rank">{i}</div><div><div class="name">{html.escape(rname(reg, lang))}</div>'
                   f'<div class="pct">{pr:.0%}<small>{t["match"]}</small></div></div></div><div class="spots"><div class="whym"><span>{t["why_title"]}</span><ul>{why}</ul></div>{rows}<div class="more">{t["allspots"]}（{len(allr)}）→</div></div></div></div>')
    out.append("</div>")
    qs = "?" + urlencode({"m": m, "d": int(days), "b": int(budget or 0), "c": cu, "p": party, "f": int(bool(first)), "s": ",".join(str(int(x)) for x in scores), "l": lang, "v": v})
    out.append(f'<i id="tjq" hidden data-q="{html.escape(qs, quote=True)}"></i>')
    out.append(f'<div class="share"><button type="button" data-ok="{html.escape(t["copied"], quote=True)}" onclick="{html.escape(f"tjCopy({json.dumps(qs)},this)", quote=True)}">{t["share"]}</button><small>{t["share_hint"]}</small></div>')
    out.append(f'{model_note(m, lang)}{note_html(t)}')
    blk = p.groupby(p.index.map(BLOCKS[m])).sum().sort_values(ascending=False, kind="stable")
    bars = "".join(f'<div class="bar"><span class="l">{html.escape(bname(m, k, lang))}</span><span class="t"><span class="f" style="width:{val / blk.max() * 100:.0f}%"></span></span><span class="v">{val:.0%}</span></div>' for k, val in blk.items())
    side = compare_html(m, lang, list(p.index[:3]), list(p.values[:3])) + f'<div class="blk blk2"><h3>{t["blk"]}</h3>{bars}</div>'
    return "".join(out), side      # 右の列(結果カード) / 左の列(条件の枠の下: 比較・ブロック別の相性)

# ---------------- ④ エリアのスポット一覧（分類表・絞り込み・ベストシーズンつき） / 検索結果 / お気に入り ----------------
def catbanner(key, m):          # カテゴリ見出しバーの写真（images/cat/）。神社・寺院は国別
    k = f"{key}_{m}" if key in ("shrine", "landmark") else key
    return asset(f"images/cat/{k}.jpg") if os.path.exists(os.path.join(BASE, "images", "cat", f"{k}.jpg")) else ""
AREAH = dict(ja=("{reg}に泊まる", "予約サイトを選んで、{reg}の宿泊先をまとめて探せます。", "{reg}のホテルを探す"),
             zh=("住在{reg}", "選擇訂房網站，一次搜尋{reg}的住宿。", "搜尋{reg}的飯店"),
             en=("Stay in {reg}", "Choose a booking site to search places to stay in {reg}.", "Find hotels in {reg}"))
AREAC = dict(ja=("{reg}を車ではしる", "{reg}で使えるレンタカー予約サイトと、出発地ごとの検索ページをまとめて開けます。", "{reg}のレンタカーを探す"),
             zh=("開車暢遊{reg}", "一次查看{reg}可用的租車預約網站，以及各取車地點的搜尋頁面。", "搜尋{reg}的租車"),
             en=("Drive around {reg}", "Open car rental booking sites for {reg}, plus search pages by pick-up location.", "Find rental cars in {reg}"))
AREAT = dict(ja=("{reg}内で移動する", "電車・バス・タクシーの検索サイトと公式アプリを、{reg}で特に便利なものと合わせてまとめて探せます。", "{reg}の交通手段を探す"),
             zh=("在{reg}移動", "一次查看電車、公車、計程車的查詢網站與官方 App，並列出在{reg}特別好用的服務。", "搜尋{reg}的交通方式"),
             en=("Get around {reg}", "Find train, bus and taxi search sites and official apps, including the ones that work best in {reg}.", "Find transport in {reg}"))
NGEN_T = dict(ja=("ジャンルを選択する", "すべて"), zh=("選擇類型", "全部"), en=("Choose a genre", "All"))
def ngen_html(lang, g, key="nature"):          # カテゴリの先頭: ジャンルで絞り込むボタン（自然: 海/山/その他、博物館・美術館、動物園・水族館、アクティビティ）
    ti, al = NGEN_T[lang]; li = {"ja": 0, "zh": 1, "en": 2}[lang]; opts = NGEN if key == "nature" else SUBGEN[key]
    btn = lambda k, lb, n: (f'<button type="button" class="ngb{" on" if not k else ""}" data-g="{k}" aria-pressed="{"true" if not k else "false"}"{" disabled" if not n else ""} '
                            f'onclick="tjGen(this)"><span>{lb}</span><em>{n}</em></button>')
    b = btn("", al, len(g)) + "".join(btn(k, x[li], int((g["ngen"] == k).sum())) for k, *x in opts)
    return (f'<div class="ngsel" data-k="{key}"><h4><i aria-hidden="true"></i><span>{ti}</span><i aria-hidden="true"></i></h4>'
            f'<div class="ngbs" role="group" aria-label="{html.escape(ti, quote=True)}" style="--n:{len(opts) + 1}">{b}</div></div>')
def region_page(m, lang, reg): return _region_page(m, lang, reg, datetime.date.today().isoformat())
@functools.lru_cache(maxsize=256)
def _region_page(m, lang, reg, day):
    d, t = D[m], TX(m, lang); s = d["spots"][d["spots"].region == reg].drop_duplicates("spot").sort_values("tourism_value_score", ascending=False, kind="stable"); secs, trs = [], []; idx = 0
    has_new = bool((s["new_within_1y_flag"] == 1).any())
    for key, ic, *_ in CATS:
        g = s[s["cat"] == key]
        if g.empty: continue
        rows = []
        for _, r in g.iterrows(): rows.append(spot_row(m, lang, r, reg, i=idx)); idx += 1
        if key == "nature" or key in SUBGEN: rows.insert(0, ngen_html(lang, g, key))
        secs.append(f'<section class="cat fold" id="cat-{key}"><h3 role="button" tabindex="0" title="{html.escape(t["fold_tip"], quote=True)}" onclick="tjFold(this)" onkeydown="if(event.key===\'Enter\')tjFold(this)" style="--bn:url(\'{catbanner(key, m)}\')"><span>{ic}</span>{catname(lang, key)}<em data-t="{t["cnt"]}">{t["cnt"].format(n=len(g))}</em><i class="chev" aria-hidden="true"></i></h3><div class="spots">{"".join(rows)}</div></section>')
        go_ = f"document.getElementById('cat-{key}').scrollIntoView({{behavior:'smooth',block:'start'}});return false;"
        trs.append(f'<tr class="row" onclick="{html.escape(go_, quote=True)}"><td><a href="#" onclick="{html.escape(go_, quote=True)}">{ic} {catname(lang, key)}</a></td><td class="n">{len(g)}</td></tr>')
    go2 = lambda key: html.escape(f"tjFold(document.querySelector('#cat-{key} h3'),1);return false;", quote=True)
    cells = "".join(f'<a href="#" onclick="{go2(k)}"><span class="cn">{CATICON[k]}{catname(lang, k)}</span><b>{n}</b></a>' for k, n in [(c[0], int((s["cat"] == c[0]).sum())) for c in CATS] if n)
    fr = lambda lb, ctl: f'<label class="frow"><span class="fl">{lb}</span><span class="fc">{ctl}</span></label>'
    catopts = "".join(f"<option value=\"{k}\">{catname(lang, k)}</option>" for k in s["cat"].unique() if k in CATICON)
    tools = (f'<div class="fltsec"><h3>{t["flt_title"]}</h3><div class="tools frows">'
             + fr(t["fl_q"], f'<input type="search" class="f-q" placeholder="{html.escape(t["f_q"], quote=True)}" oninput="tjFilter(this)">')
             + fr(t["fl_cat"], f'<select class="f-cat" onchange="tjFilter(this)"><option value="">{t["f_cat"]}</option>{catopts}</select>')
             + fr(t["fl_sort"], f'<select class="f-sort" onchange="tjFilter(this)"><option value="def">{t["sort_def"]}</option><option value="name">{t["sort_name"]}</option></select>')
             + fr(t["fl_new"], f'<select class="f-new" onchange="tjFilter(this)"><option value="">{t["new_all"]}</option><option value="new">{t["new_only"]}</option></select>')
             + f'<span class="f-n" data-t="{t["f_shown"]}">{t["f_shown"].format(n=len(s))}</span><span class="f-none">{t["f_none"]}</span></div></div>')
    rn_ = html.escape(rname(reg, lang))
    table = (f'<div class="guidebox catbox"><div class="catsec"><h3 class="big">{t["tbl_title"].format(reg=rn_)}</h3><p class="sn">{t["tbl_hint"]}</p><div class="catgrid">{cells}</div>'
             f'<p class="cattot"><span>{t["tbl_total"]}</span><b>{len(s)}</b></p></div>{tools}</div>')
    rn_ = html.escape(rname(reg, lang)); ah = AREAH[lang]; at = AREAT[lang]
    ahotel = (f'<div class="ahbox ahtr"><h3>{at[0].format(reg=rn_)}</h3><div class="ahrow"><p>{at[1].format(reg=rn_)}</p>'           # ○○内で移動する（交通手段のページへ）
              f'<a class="areahotel" href="#" onclick="{jsgo("hotel", reg, "@trans")};return false">{at[2].format(reg=rn_)}</a></div></div>')
    ahotel += (f'<div class="ahbox"><h3>{ah[0].format(reg=rn_)}</h3><div class="ahrow"><p>{ah[1].format(reg=rn_)}</p>'
              f'<a class="areahotel" href="#" onclick="{jsgo("hotel", reg, "@area")};return false">{ah[2].format(reg=rn_)}</a></div></div>')
    ac = AREAC[lang]
    ahotel += (f'<div class="ahbox ahcar"><h3>{ac[0].format(reg=rn_)}</h3><div class="ahrow"><p>{ac[1].format(reg=rn_)}</p>'
               f'<a class="areahotel" href="#" onclick="{jsgo("hotel", reg, "@car")};return false">{ac[2].format(reg=rn_)}</a></div></div>')
    bg = region_photo(reg); cover = f"background-image:url('{bg}');{bgpos(reg)}" if bg else f"background-image:url('{cover_svg(m, 1)}')"
    return (f'<div class="pg"><div class="pgcover" style="{cover}"><div><div class="pgsub">{t["regions"]}</div><h2>{html.escape(rname(reg, lang))}</h2><p>{t["cnt"].format(n=len(s))}</p></div></div>'
            f'<div class="guidebox">{iconic_html(m, reg, lang)}{weather_html(reg, lang)}{season_html(reg, lang, t)}{ahotel}</div>{table}{"".join(secs)}{note_html(t)}</div>')

FAVX = dict(ja=dict(k="FAVORITES", s1="旅程の設定と書き出し", d1="出発日と日数を入れると、日ごとの予定表とカレンダーができます。カレンダー（.ics）・PDF・テキストに書き出せます。",
                   s2="保存したスポット", s3="旅程表", w2="保存したスポット（{n}）", d3="日程を選んだスポットが、日ごとの予定表と月のカレンダーに並びます。"),
            zh=dict(k="FAVORITES", s1="行程設定與匯出", d1="填入出發日與天數後，會產生每日行程表與月曆。可匯出為行事曆（.ics）、PDF 或文字。",
                   s2="已收藏的景點", s3="行程表", w2="已收藏的景點（{n}）", d3="已選擇日程的景點，會依日期排入每日行程表與月曆。"),
            en=dict(k="FAVORITES", s1="Trip settings and export", d1="Enter a start date and the number of days to build a daily schedule and calendar. Export it to your calendar (.ics), a PDF or plain text.",
                   s2="Saved spots", s3="Itinerary", w2="Saved spots ({n})", d3="Spots with a day assigned appear here in a daily schedule and a monthly calendar."))
def fav_page(m, lang, favs):
    """お気に入り・旅程（ホテル・旅の準備ページと同じ意匠: 欧文の大見出し + 金枠 + 番号つきの濃色見出し帯）"""
    t = TX(m, lang); L = LBL[lang]; X = FAVX[lang]; groups = {}; ea = lambda x: html.escape(x, quote=True)
    for reg, sp in favs:                                  # 追加した順に、エリアごとにまとめる
        groups.setdefault(reg, []).append(sp)
    secs = []; n_all = 0
    for reg, sps in groups.items():
        g = D[mkt_of(reg)]["spots"]; rows = []
        for j, sp in enumerate(sps):
            hit = g[(g.region == reg) & (g.spot == sp)]
            if not len(hit): continue
            ex = (f'<div class="plx"><select class="daysel" data-reg="{ea(reg)}" data-sp="{ea(sp)}" data-rn="{ea(rname(reg, lang))}" aria-label="{L["plan_dayhd"]}" onchange="tjPlanSet(this)"></select>'
                  f'<label class="tm">{L["plan_time"]}<input type="time" class="tmsel" data-reg="{ea(reg)}" data-sp="{ea(sp)}" onchange="tjPlanSet(this)"></label></div>')
            rows.append(spot_row(mkt_of(reg), lang, hit.iloc[0], reg, i=j, extra=ex))
        if rows:
            n_all += len(rows); ph = region_photo(reg); fx, fy = FOCUS.get(reg, (50, 50))
            th = f'<img class="favth" src="{ph}" alt="" loading="lazy" style="object-position:{fx}% {fy}%">' if ph else ""
            secs.append(f'<section class="cat favg"><h3 data-rg="{ea(rname(reg, lang))}">{th}<span class="favrn"><small>{CN[mkt_of(reg)][lang]}</small>{html.escape(rname(reg, lang))}</span>'
                        f'<em>{t["cnt"].format(n=len(rows))}</em></h3><div class="spots">{"".join(rows)}</div></section>')
    if not secs:
        head = lux_head(X["k"], t["fav_title"], t["fav_sub"])
        return lux_page("planner favpg", head, [f'<div class="luxbody"><div class="res-empty">{t["fav_empty"]}</div></div>'])
    top = (f'<div class="plantop"><label>{L["plan_start"]}<input type="date" id="plan-start" onchange="tjPlanSet(this)"></label>'
           f'<label>{L["plan_days"]}<input type="number" id="plan-days" min="1" max="14" onchange="tjPlanSet(this)"></label>'
           f'<button type="button" class="pri" onclick="tjPlanIcs()">{L["plan_ics"]}</button><button type="button" onclick="window.print()">{L["plan_pdf"]}</button>'
           f'<button type="button" data-ok="{ea(t["copied"])}" onclick="tjPlanText(this)">{L["plan_copy"]}</button><button type="button" onclick="tjFavClear()">{t["fav_clear"]}</button><span id="planmsg"></span></div>')
    attrs = " ".join(f'data-{k}="{ea(v)}"' for k, v in dict(lang=lang, day=L["plan_day"], none=L["plan_none"], needdate=L["plan_needdate"], un=L["plan_un"], route=L["plan_route"],
                                                           emptysched=L["plan_empty_sched"], note=L["plan_note"], sched=L["plan_sched"]).items())
    ways = [("fav-plan", X["s1"]), ("fav-spots", X["w2"].format(n=n_all)), ("fav-sched", X["s3"])]
    head = lux_head(X["k"], t["fav_title"], t["fav_sub"], ways)
    body = [lux_sec(1, "fav-plan", X["s1"], X["d1"], top),
            lux_sec(2, "fav-spots", X["s2"], L["plan_hint"], "".join(secs), right=t["cnt"].format(n=n_all)),
            lux_sec(3, "fav-sched", X["s3"], X["d3"], '<div class="planout" id="planout"></div>')]
    return lux_page("planner favpg", head, body, attrs=attrs)

SRCH = dict(ja=("SEARCH", "エリアページ", "条件に合うエリアのページです。カードを押すと、そのエリアのスポット一覧へ移動します。", "名前が一致したスポットです。地図・写真・公式サイトをそのまま開けます。", "{n}件", "別のキーワードで、もう一度お試しください。"),
            zh=("SEARCH", "地區頁面", "符合條件的地區頁面。點選卡片即可前往該地區的景點列表。", "名稱相符的景點，可直接開啟地圖、照片與官方網站。", "{n} 筆", "請換個關鍵字再試一次。"),
            en=("SEARCH", "Region pages", "Region pages that match. Tap a card to open that region's list of spots.", "Spots whose names match. Open the map, photos or official site directly.", "{n}", "Please try another keyword."))
_SREC = {}
def _spot_rec(m, reg, spot):          # (エリア, スポット) -> CSVの行。検索のたびに表全体を走査しない
    if m not in _SREC:
        g = D[m]["spots"]; d_ = {}; d2 = {}
        for _, r in g.iterrows(): d_.setdefault((r["region"], r["spot"]), r); d2.setdefault(r["spot"], r)
        _SREC[m] = (d_, d2)
    d_, d2 = _SREC[m]; r = d_.get((reg, spot)); return r if r is not None else d2.get(spot)
@functools.lru_cache(maxsize=128)
def search_page(m, lang, q):
    t = TX(m, lang); S = SRCH[lang]; hits = search_all(q, m, lang); nsp = sum(len(h[2]) for h in hits); secs = []; ways = []
    qh = html.escape(q); title = f'{t["sres"]}<span class="luxq">「{qh}」</span>' if lang != "en" else f'{t["sres"]}<span class="luxq">“{qh}”</span>'
    if not hits:
        head = lux_head(S[0], title, S[5])
        return lux_page("srch", head, [f'<div class="luxbody"><div class="res-empty">{t["nores"]}</div></div>'])
    for mk_ in (m, OTHER[m]):
        hs = [h for h in hits if h[0]["m"] == mk_]
        if not hs: continue
        cards = []
        for e, rhit, shits, chits in hs:
            why = []
            if rhit: why.append(f'<b>{t["why_region"]}</b>')
            if chits: why.append(f'<b>{t["why_cat"]}</b>' + ", ".join(catname(lang, c) for c in chits))
            if shits: why.append(f'<b>{t["why_spot"]}</b>' + "、".join(html.escape(x) for x in shits[:4]) + (f' {t["andmore"].format(n=len(shits) - 4)}' if len(shits) > 4 else ""))
            fx, fy = FOCUS.get(e["reg"], (50, 50)); rn_ = html.escape(rname(e["reg"], lang))
            go_ = jsgo("region", e["reg"])
            cards.append(f'<div class="hit hitx" role="link" tabindex="0" onclick="{go_}" onkeydown="if(event.key===\'Enter\'){{{go_}}}"><img src="{region_photo(e["reg"])}" alt="" loading="lazy" decoding="async" style="object-position:{fx}% {fy}%">'
                         f'<div class="hitin"><div class="cn">{CN[mk_][lang]}</div><h4>{rn_}</h4><div class="why">{"".join(f"<p>{w}</p>" for w in why)}</div></div><span class="hgo" aria-hidden="true">&#8594;</span></div>')
        sid = f"srch-{mk_}"; ttl = f'{S[1]} — {CN[mk_][lang]}'
        ways.append((sid, f'{ttl}（{len(hs)}）'))
        secs.append(lux_sec(len(secs) + 1, sid, ttl, S[2], f'<div class="hitgrid">{"".join(cards)}</div>', right=S[4].format(n=len(hs))))
    rows = []; nrows = 0          # 表示するのは先頭80件だけ。行のHTMLもその分だけ作る（以前は全件を作ってから切り捨てていて遅かった）
    for e, rhit, shits, chits in hits:
        for sname in shits:
            nrows += 1
            if len(rows) < 80:
                r_ = _spot_rec(e["m"], e["reg"], sname)
                if r_ is not None: rows.append(spot_row(e["m"], lang, r_, e["reg"], show_reg=True))
    if rows:
        ways.append(("srch-spots", f'{t["sec_spots"]}（{nrows}）'))
        secs.append(lux_sec(len(secs) + 1, "srch-spots", t["sec_spots"], S[3], f'<div class="spots">{"".join(rows)}</div>', right=S[4].format(n=nrows)))
    head = lux_head(S[0], title, t["pagesfound"].format(p=len(hits), s=nsp), ways)
    return lux_page("srch", head, secs)

# ---------------- ⑤ ホテル予約サイト一覧 ----------------
HOTELS = {  # key: (日本語名, 中文名, English, 種別, URL雛形 or ドメイン)。urlは各サイトの検索URL、siteはGoogleでそのサイト内を検索
    "rakuten": ("楽天トラベル", "樂天旅遊", "Rakuten Travel", "url", "https://kw.travel.rakuten.co.jp/keyword/Search.do?f_query={q}&lang=ja"),
    "jalan": ("じゃらん", "Jalan（じゃらん）", "Jalan", "url", "https://www.jalan.net/uw/uwp2011/uww2011init.do?keyword={q}&distCd=01&screenId=FWPCTOP"),
    "ikyu": ("一休.com", "一休.com", "Ikyu.com", "url", "https://www.ikyu.com/search/?kw={q}"),
    "yahoo": ("Yahoo!トラベル", "Yahoo! 旅遊（日本）", "Yahoo! Travel Japan", "url", "https://travel.yahoo.co.jp/search/?kw={q}"),
    "trip": ("Trip.com", "Trip.com 攜程", "Trip.com", "url", "https://www.trip.com/hotels/list?keyword={q}"),
    "booking": ("Booking.com", "Booking.com", "Booking.com", "url", "https://www.booking.com/searchresults.html?ss={q}"),
    "agoda": ("Agoda", "Agoda 安可達", "Agoda", "url", "https://www.agoda.com/search?textToSearch={q}"),
    "expedia": ("Expedia", "Expedia 智遊天下", "Expedia", "url", "https://www.expedia.com/Hotel-Search?destination={q}"),
    "hotels": ("Hotels.com", "Hotels.com", "Hotels.com", "url", "https://www.hotels.com/Hotel-Search?destination={q}"),
    "airbnb": ("Airbnb", "Airbnb", "Airbnb", "url", "https://www.airbnb.com/s/{q}/homes"),
    "google": ("Google ホテル", "Google 飯店", "Google Hotels", "url", "https://www.google.com/travel/hotels/{q}"),
    "tripadvisor": ("トリップアドバイザー", "Tripadvisor 貓途鷹", "Tripadvisor", "url", "https://www.tripadvisor.com/Search?q={q}")}
HORDER = {"taiwan": ["rakuten", "booking", "agoda", "expedia", "trip", "hotels", "airbnb", "google", "tripadvisor", "yahoo"],
          "japan": ["trip", "agoda", "booking", "expedia", "hotels", "airbnb", "google", "tripadvisor", "rakuten", "jalan", "ikyu", "yahoo"]}
PLACE = json.load(open(os.path.join(BASE, "data", "place.json"), encoding="utf-8"))      # スポット → 市区町村（台湾は鄉鎮市區）
def place_term(m, reg, spot):
    """ホテル検索に使う地名。スポットのある市区町村（不明ならエリア名）。区だけだと別の市と紛れるので、都道府県名・県市名を前に付ける"""
    c = PLACE.get(m, {}).get(spot)
    if not c or spot in DUPNAME.get(m, ()): return reg          # 同じ名前が複数のエリアにあるスポット（台湾の「白沙灣」など）は市区町村を特定できないのでエリア名
    return reg + c if (m == "taiwan" or c.endswith("区")) else c
JPCHR = str.maketrans({"縣": "県", "鄉": "郷", "區": "区", "臺": "台", "鎮": "町", "與": "与"})
def enc_term(term, charset):
    """検索語をURL用に符号化。日本の古い検索ページ（楽天トラベル・じゃらん）は EUC-JP で受け取るため、UTF-8のままだと文字化けする"""
    if charset == "utf-8": return quote(term)
    for t in (term, term.translate(JPCHR)):
        try: return quote(t.encode(charset))
        except UnicodeEncodeError: pass
    return quote(term)
ENC = {"rakuten": "euc-jp", "jalan": "euc-jp"}
def hotel_url(key, term):
    kind, v = HOTELS[key][3], HOTELS[key][4]
    if kind == "url": return v.format(q=enc_term(term, ENC.get(key, "utf-8")))
    kw = "hotel" if key == "trip" else "ホテル"
    return "https://www.google.com/search?q=" + quote(f"{term} {kw} site:{v}")

HCOPY = dict(ja="検索語「{t}」をコピーしました。検索欄が空のときは貼り付けてください。", zh="已複製搜尋詞「{t}」。若搜尋欄是空的，請貼上。", en="Copied “{t}”. If the search box is empty, just paste it.")
HLBL = dict(ja=("近くのホテルを探す", "予約サイトを選ぶ"), zh=("搜尋附近的飯店", "選擇訂房網站"), en=("Find hotels nearby", "Choose a booking site"))
AREASUB = dict(ja="{term}の宿泊先を探せます。予約サイトを選ぶと、「{term}」で検索したページが新しいタブで開きます。", zh="搜尋{term}的住宿。選擇訂房網站後，會以「{term}」搜尋並在新分頁開啟。", en="Find places to stay in {term}. Choose a booking site to open a search for “{term}” in a new tab.")
CARL = dict(
    ja=dict(k="レンタカーを探す", sub="{reg}で使えるレンタカー予約サイトです。サイトを選ぶと新しいタブで開きます。",
            s1="予約サイトを選ぶ（{reg}全域）", s2="出発地から探す", deep="{reg}のページ", top="サイトのトップ",
            kind=dict(cmp="比較・予約", co="レンタカー会社", intl="海外向け予約"), pj="じゃらんレンタカーで検索", pg="Googleマップで周辺の店舗を表示", isl="離島",
            note="予約サイトのトップが開く場合は、サイト内の検索欄にエリア名を入れてください（エリア名は自動でコピーされます）。取り扱い店舗・料金・在庫は各サイトでご確認ください。離島や小さな町では、時期によって掲載プランがない場合があります。"),
    zh=dict(k="搜尋租車", sub="以下是{reg}可用的租車預約網站，點選後會在新分頁開啟。",
            s1="選擇預約網站（{reg}全區）", s2="依取車地點搜尋", deep="{reg}頁面", top="網站首頁",
            kind=dict(cmp="比價・預約", co="租車公司", intl="國際預約"), pj="在 Jalan 租車搜尋", pg="在 Google 地圖顯示附近門市", isl="離島",
            note="若開啟的是網站首頁，請在站內搜尋欄輸入地區名稱（地區名稱會自動複製）。門市、價格與庫存請以各網站為準。離島或小鎮在部分時期可能沒有可預約的方案。"),
    en=dict(k="Find a rental car", sub="Car rental booking sites you can use in {reg}. Each opens in a new tab.",
            s1="Choose a booking site (all of {reg})", s2="Search by pick-up location", deep="{reg} page", top="Top page",
            kind=dict(cmp="Comparison", co="Rental company", intl="International"), pj="Search on Jalan Rent-a-Car", pg="Nearby shops on Google Maps", isl="Island",
            note="If a site opens on its top page, type the area name into its search box (the name is copied for you). Check shops, prices and availability on each site. Small towns and islands may have no plans listed at some times of year."))
CARD = dict(ja=("比較サイト・レンタカー会社・海外向け予約サイトの順に並べています。", "市区町村や空港・駅ごとの検索ページを直接開きます。"),
            zh=("依比價網站、租車公司、國際預約網站的順序排列。", "直接開啟各鄉鎮市區、機場與車站的搜尋頁面。"),
            en=("Listed as comparison sites, rental companies, then international booking sites.", "Open a search page for each city, airport or station directly."))
def _hsite(i, url, name, small, extra="", cls="", tag=""):
    ea = lambda x: html.escape(x, quote=True)
    return (f'<a class="hsite{cls}" href="{ea(url)}" target="_blank" rel="noopener noreferrer"{extra}>'
            f'<span class="hn">{i + 1:02d}</span><span class="ht"><b>{html.escape(name)}{tag}</b><small>{small}</small></span><span class="ha">&#8599;</span></a>')
@functools.lru_cache(maxsize=256)
def car_page(m, lang, reg):
    """⑤' レンタカー予約サイト一覧。日本と台湾でサイトを分け(rentacar.py)、出発地は北から順・離島は最後に並べる"""
    L = CARL[lang]; rn = html.escape(rname(reg, lang)); term = rname(reg, "en") if lang == "en" else reg; te = html.escape(term, quote=True); ea = lambda x: html.escape(x, quote=True)
    cp = f' data-q="{te}" data-t="{ea(HCOPY[lang].format(t=term))}" onclick="tjCopy(this)"'
    cards = [_hsite(i, url, name, f'{L["kind"][kind]} ・ {(L["deep"] if deep else L["top"]).format(reg=rn)}', cp, f" k-{kind}")
             for i, (key, name, kind, url, deep) in enumerate(rentacar.sites(m, lang, reg))]
    pts = [_hsite(i, url, name, L["pj"] if m == "japan" else L["pg"], cls=" island" if isl else "", tag=f'<em class="isl">{L["isl"]}</em>' if isl else "")
           for i, (name, url, isl) in enumerate(rentacar.points(m, lang, reg))]
    s1 = L["s1"].format(reg=rn); n = SRCH[lang][4]
    secs = [lux_sec(1, "car-sites", s1, CARD[lang][0], f'<div class="hgrid">{"".join(cards)}</div>', right=n.format(n=len(cards)))]; ways = [("car-sites", s1)]
    if pts:
        secs.append(lux_sec(2, "car-points", L["s2"], CARD[lang][1], f'<div class="hgrid">{"".join(pts)}</div>', right=n.format(n=len(pts)))); ways.append(("car-points", L["s2"]))
    head = lux_head("RENT A CAR", rn, L["sub"].format(reg=rn), ways if len(ways) > 1 else (), sub=L["k"])
    return lux_page("carpg", head, secs, f'<div class="note luxnote">{L["note"]}</div>')

# ---------------- メニュー「日本（台湾）のホテルを探す」「日本（台湾）のレンタカーを探す」: 国全体のページ ----------------
CTRY = dict(
    ja=dict(hk="{c}のホテルを探す", hs1="予約サイトを選ぶ（{c}全域）", hs2="エリアから探す", hd2="エリアを選ぶと、そのエリアで検索した予約サイトの一覧へ移動します。",
            hlead="国内・海外の主な予約サイトで、{c}全域の宿泊先を探せます。行き先が決まっている場合は、下の「エリアから探す」から選んでください。",
            ck="{c}のレンタカーを探す", cs1="予約サイトを選ぶ（{c}全域）", cs2="エリアから探す", cd1="比較サイト・レンタカー会社・海外向け予約サイトの順に並べています。一部の会社は営業エリアが限られます。",
            cd2="エリアを選ぶと、そのエリアで使える予約サイトと出発地ごとの検索ページへ移動します。", clead="{c}で使えるレンタカー予約サイトです。借りる場所が決まっている場合は、下の「エリアから探す」から選んでください。",
            go_h="{reg}のホテルを探す", go_c="{reg}のレンタカーを探す", ltd="一部エリアのみ"),
    zh=dict(hk="搜尋{c}的飯店", hs1="選擇訂房網站（{c}全區）", hs2="依區域搜尋", hd2="選擇區域後，會前往以該區域搜尋的訂房網站列表。",
            hlead="以國內外主要訂房網站搜尋{c}全區的住宿。若已決定目的地，請從下方「依區域搜尋」選擇。",
            ck="搜尋{c}的租車", cs1="選擇預約網站（{c}全區）", cs2="依區域搜尋", cd1="依比價網站、租車公司、國際預約網站的順序排列。部分公司僅於特定區域營業。",
            cd2="選擇區域後，會前往該區域可用的預約網站與各取車地點的搜尋頁面。", clead="{c}可用的租車預約網站。若已決定取車地點，請從下方「依區域搜尋」選擇。",
            go_h="搜尋{reg}的飯店", go_c="搜尋{reg}的租車", ltd="僅部分區域"),
    en=dict(hk="Find hotels in {c}", hs1="Choose a booking site (all of {c})", hs2="Search by area", hd2="Pick an area to see booking sites searched for that area.",
            hlead="Search places to stay anywhere in {c} on major booking sites. If you already know where you're going, pick an area below.",
            ck="Find rental cars in {c}", cs1="Choose a booking site (all of {c})", cs2="Search by area", cd1="Listed as comparison sites, rental companies, then international booking sites. Some companies only operate in certain areas.",
            cd2="Pick an area to see the booking sites and pick-up locations for that area.", clead="Car rental booking sites you can use in {c}. If you know where you'll pick up, choose an area below.",
            go_h="Hotels in {reg}", go_c="Rental cars in {reg}", ltd="Some areas only"))
def _area_cards(m, lang, act, label):
    """エリア（都道府県・県市）の写真カード。北から順"""
    regs = sorted(set(D[m]["spots"].region), key=lambda r: (r in rentacar.TW_ISLAND, -LAT.get(r, 0))); cards = []
    for reg in regs:
        fx, fy = FOCUS.get(reg, (50, 50)); rn_ = html.escape(rname(reg, lang)); go_ = jsgo("hotel", reg, act)
        cards.append(f'<div class="hit hitx" role="link" tabindex="0" onclick="{go_}" onkeydown="if(event.key===\'Enter\'){{{go_}}}"><img src="{region_photo(reg)}" alt="" loading="lazy" decoding="async" style="object-position:{fx}% {fy}%">'
                     f'<div class="hitin"><div class="cn">{CN[m][lang]}</div><h4>{rn_}</h4><div class="why"><p>{html.escape(label.format(reg=rname(reg, lang)))}</p></div></div><span class="hgo" aria-hidden="true">&#8594;</span></div>')
    return f'<div class="hitgrid">{"".join(cards)}</div>', len(cards)
@functools.lru_cache(maxsize=16)
def hotels_country_page(m, lang):
    t = TX(m, lang); C = CTRY[lang]; c = guide.COUNTRY[lang][m]; term = CN[m]["en"] if lang == "en" else {"japan": "日本", "taiwan": "台湾" if lang == "ja" else "台灣"}[m]
    cp = f' data-q="{html.escape(term, quote=True)}" data-t="{html.escape(HCOPY[lang].format(t=term), quote=True)}" onclick="tjCopy(this)"'
    cards = [_hsite(i, hotel_url(key, term), {"ja": HOTELS[key][0], "zh": HOTELS[key][1], "en": HOTELS[key][2]}[lang], t["hdirect"], cp) for i, key in enumerate(HORDER[m])]
    grid, n = _area_cards(m, lang, "@area", C["go_h"]); n_ = SRCH[lang][4]
    secs = [lux_sec(1, "hc-sites", C["hs1"].format(c=c), HOTD[lang], f'<div class="hgrid">{"".join(cards)}</div>', right=n_.format(n=len(cards))),
            lux_sec(2, "hc-areas", C["hs2"], C["hd2"], grid, right=n_.format(n=n))]
    head = lux_head("HOTELS", html.escape(C["hk"].format(c=c)), C["hlead"].format(c=c), [("hc-sites", C["hs1"].format(c=c)), ("hc-areas", C["hs2"])], sub=m.upper())
    return lux_page("hotelx", head, secs, f'<div class="note luxnote">{t["hnote"]}</div>')
@functools.lru_cache(maxsize=16)
def cars_country_page(m, lang):
    C = CTRY[lang]; L = CARL[lang]; c = guide.COUNTRY[lang][m]; n_ = SRCH[lang][4]
    cards = [_hsite(i, url, name, f'{L["kind"][kind]}' + (f' ・ {C["ltd"]}' if ltd else ""), cls=f" k-{kind}") for i, (key, name, kind, url, ltd) in enumerate(rentacar.country_sites(m, lang))]
    grid, n = _area_cards(m, lang, "@car", C["go_c"])
    secs = [lux_sec(1, "cc-sites", C["cs1"].format(c=c), C["cd1"], f'<div class="hgrid">{"".join(cards)}</div>', right=n_.format(n=len(cards))),
            lux_sec(2, "cc-areas", C["cs2"], C["cd2"], grid, right=n_.format(n=n))]
    head = lux_head("RENT A CAR", html.escape(C["ck"].format(c=c)), C["clead"].format(c=c), [("cc-sites", C["cs1"].format(c=c)), ("cc-areas", C["cs2"])], sub=m.upper())
    return lux_page("carpg", head, secs, f'<div class="note luxnote">{L["note"]}</div>')

@functools.lru_cache(maxsize=16)
def trans_country_page(m, lang):
    """メニュー「日本（台湾）の交通手段を探す」: 電車・バス・タクシーの検索サイト / 配車アプリ（transport.py）"""
    return transport.page(m, lang, guide.COUNTRY[lang][m], lux_head, lux_sec, lux_page)

@functools.lru_cache(maxsize=256)
def trans_region_page(m, lang, reg):
    """エリアページの「○○の交通手段を探す」: そのエリアで便利なアプリ・サイト＋国全体の一覧（transport.py）"""
    return transport.page(m, lang, guide.COUNTRY[lang][m], lux_head, lux_sec, lux_page, reg=reg, rname=rname(reg, lang))

HOTD = dict(ja="国内・海外の主な予約サイトです。料金や空室は各サイトでご確認ください。", zh="國內外主要訂房網站。價格與空房請以各網站為準。", en="Major domestic and international booking sites. Check prices and availability on each site.")
def hotel_page(m, lang, reg, spot):
    if spot == "@car": return car_page(mkt_of(reg), lang, reg)
    if spot == "@trans": return trans_region_page(mkt_of(reg), lang, reg)
    t = TX(m, lang); area = spot == "@area"
    term = reg if area else place_term(m, reg, spot); title = rname(reg, lang) if area else spot; te = html.escape(term, quote=True)
    cp = f' data-q="{te}" data-t="{html.escape(HCOPY[lang].format(t=term), quote=True)}" onclick="tjCopy(this)"'
    cards = [_hsite(i, hotel_url(key, term), {"ja": HOTELS[key][0], "zh": HOTELS[key][1], "en": HOTELS[key][2]}[lang], t["hdirect"], cp) for i, key in enumerate(HORDER[m])]
    sub = (AREASUB[lang] if area else t["hsub"]).format(spot=html.escape(title), reg=html.escape(rname(reg, lang)), term=html.escape(term))
    k = HLBL[lang][0] + ("" if area else f'<span class="luxreg">{html.escape(term)}</span>')
    head = lux_head("HOTELS", html.escape(title), sub, sub=k)
    return lux_page("hotelx", head, [lux_sec(1, "hotel-sites", HLBL[lang][1], HOTD[lang], f'<div class="hgrid">{"".join(cards)}</div>', right=SRCH[lang][4].format(n=len(cards)))], f'<div class="note luxnote">{t["hnote"]}</div>')

# ---------------- ② 地図（実際の境界データから作ったSVG。各行政区をクリックで選択） ----------------
MAPS = json.load(open(os.path.join(BASE, "data", "maps.json"), encoding="utf-8"))
LABEL_MIN = {"japan": 900, "taiwan": 700}          # この面積以上のエリアは常にラベル表示（小さいエリアはマウスを乗せると表示）
HUES = [205, 160, 45, 350, 275, 100, 20]
@functools.lru_cache(maxsize=16)
def map_card(m, lang, big=False):
    t = TX(m, lang); M = MAPS[m]; have = set(D[m]["spots"].region); blocks = list(dict.fromkeys(BLOCKS[m].values())); hue = {b: HUES[i % len(HUES)] for i, b in enumerate(blocks)}
    fs = (12 if m == "taiwan" else 11) if lang != "en" else (10.5 if m == "taiwan" else 9.5); fs *= 1.75 if big else 1; g = []
    hits = []
    for r in M["regions"]:                                  # 小さいエリア（離島など）は、透明で太い輪郭をクリック範囲として足す（本体の下に敷く）
        if r["n"] in have and r["a"] < 200:
            sw = 30 if r["a"] < 60 else 18
            hits.append(f'<path class="hit" d="{r["d"]}" fill="none" stroke="#fff" stroke-opacity="0.001" stroke-width="{sw}" stroke-linejoin="round" pointer-events="all" role="button" onclick="{jsgo("region", r["n"])}"><title>{html.escape(rname(r["n"], lang))}</title></path>')
    W, H = M["w"], M["h"]; ins0 = M.get("inset")
    tw = lambda s: sum(fs if ord(ch) > 255 else fs * .56 for ch in s)        # ラベルの概算幅
    pts = {}                                                    # 各エリアの輪郭座標（ラベルが収まるか・陸地の端の位置を調べる）
    for r in M["regions"]:
        v = [float(x) for x in re.findall(r"-?\d+\.?\d*", r["d"])]; pts[r["n"]] = list(zip(v[0::2], v[1::2]))
    inside, outside, placed = [], [], []
    def hit(r):
        w = tw(rshort(r["n"], lang)) / 2 + 2; x, y = r["x"] + r["ox"], r["y"] + r["oy"]
        return any(abs(x - px) < w + pw and abs(y - py) < fs * .95 for px, py, pw in placed), (x, y, w)
    cand = [r for r in M["regions"] if r["n"] in have]
    for r in sorted(cand, key=lambda r: (not r["oy"], -r["a"])):         # 大きいエリアから順に、文字が収まり他と重ならなければエリア内に表示
        p = pts[r["n"]]; bw = max(q[0] for q in p) - min(q[0] for q in p); bh = max(q[1] for q in p) - min(q[1] for q in p)
        ok = bool(r["oy"]) or (tw(rshort(r["n"], lang)) <= bw * .62 and bh >= fs * 2.4 and r["a"] >= 300)
        if ok:
            ov, (x, y, w) = hit(r)
            if not ov or r["oy"]: placed.append((x, y, w)); inside.append(r); continue
        outside.append(r)
    allp = [q for n, p in pts.items() for q in p]
    def edge(y, side):                                          # その高さ付近の陸地の左端 / 右端
        near = [q[0] for q in allp if abs(q[1] - y) < 26] or [q[0] for q in allp]
        if ins0 and ins0[1] - 10 < y < ins0[1] + ins0[3] + 10: near = near + [ins0[0], ins0[0] + ins0[2]]
        return min(near) if side == "L" else max(near)
    sides = {"L": [], "R": []}
    for r in outside:
        near = [q["x"] for q in M["regions"] if abs(q["y"] - r["y"]) < 70]
        sides["L" if r["x"] < sum(near) / len(near) else "R"].append(r)
    gap = fs + 3.5; lab = {}; lm = rm = 0
    for sd, rs in sides.items():
        rs.sort(key=lambda r: r["y"]); ys = []
        for r in rs: ys.append(max(r["y"], (ys[-1] + gap) if ys else 8))
        over = (ys[-1] - (H - 6)) if ys else 0
        if over > 0: ys = [y - over for y in ys]
        for k in range(len(ys) - 2, -1, -1): ys[k] = min(ys[k], ys[k + 1] - gap)
        for r, y in zip(rs, ys):
            ex = edge(y, sd) + (-9 if sd == "L" else 9); lab[r["n"]] = (sd, y, ex)
            w = tw(rshort(r["n"], lang)) + 12
            if sd == "L": lm = max(lm, w - ex)
            else: rm = max(rm, ex + w - W)
    padL, padR = int(max(lm, 0)) + 4, int(max(rm, 0)) + 4
    g = []; tx = []
    for r in M["regions"]:
        n = r["n"]
        if n not in have: continue
        oc = f'onclick="{jsgo("region", n)}"'; ti = f'<title>{html.escape(rname(n, lang))}</title>'
        g.append(f'<g class="pf" role="button" tabindex="0" {oc}>{ti}<path d="{r["d"]}" fill-rule="evenodd" style="fill:hsl({hue[BLOCKS[m][n]]},42%,82%)"/></g>')
        if n in lab:
            sd, y, ex = lab[n]; anc = "end" if sd == "L" else "start"; k = 5 if sd == "L" else -5
            tx.append(f'<g class="pl" role="button" {oc}>{ti}<polyline class="ld" points="{r["x"]:.1f},{r["y"]:.1f} {ex + k:.1f},{y - fs * .32:.1f} {ex:.1f},{y - fs * .32:.1f}"/><circle class="ldd" cx="{r["x"]:.1f}" cy="{r["y"]:.1f}" r="1.8"/>'
                      f'<text class="lb al" style="text-anchor:{anc};pointer-events:auto" x="{ex + (-3 if sd == "L" else 3):.1f}" y="{y:.1f}" font-size="{fs}">{html.escape(rshort(n, lang))}</text></g>')
        else:
            tx.append(f'<text class="lb al" x="{r["x"] + r["ox"]}" y="{r["y"] + r["oy"]}" font-size="{fs}">{html.escape(rshort(n, lang))}</text>')
    ins = M.get("inset"); box = f'<rect class="inset" x="{ins[0]}" y="{ins[1]}" width="{ins[2]}" height="{ins[3]}"/>' if ins else ""
    legend = "".join(f'<span><i style="background:hsl({hue[b]},42%,82%)"></i>{html.escape(bname(m, b, lang))}</span>' for b in blocks)
    return (f'<div class="mapcard"><span class="orn"><i></i><u></u><i></i></span><h3>{t["mtitle"]}</h3><p>{t["msub"]}</p><svg class="jmap" viewBox="{-padL} 0 {W + padL + padR} {H}" xmlns="http://www.w3.org/2000/svg">{"".join(hits)}{"".join(g)}{box}{"".join(tx)}</svg>'
            f'<div class="legend">{legend}</div></div>')

SEC = {"ja": ("旅程・同行者", "予算", "こだわり（1 = 気にしない 〜 5 = 重視）"), "zh": ("行程・同行者", "預算", "偏好（1 = 不在意 〜 5 = 重視）"), "en": ("Trip and party", "Budget", "Preferences (1 = don't mind, 5 = important)")}
SECD = dict(ja=("日数・同行者・訪問経験", "1日あたりの目安金額", "好みの強さを1〜5で"), zh=("天數・同行者・造訪經驗", "每日預算的大致金額", "以1〜5表示喜好程度"), en=("Length, party and experience", "Approximate budget per day", "Rate what you like, 1 to 5"))
def sec_html(lang, i): return f'<div class="fsech"><b>{i + 1}</b><span>{SEC[lang][i]}</span><small>{SECD[lang][i]}</small></div>'
def langs_html(lang, cls, short=False):
    return "".join(f'<a href="#" class="{"on" if l == lang else ""}" onclick="{jsgo("lang", l)}">{SHORT[l] if short else LANG_NAMES[l]}</a>' for l in LANG_ORDER)
BRAND_TIP = dict(ja="日本と台湾をつなぐ旅", zh="連結日本與台灣的旅程", en="A bridge between Japan and Taiwan")
def brand_html(lang): return f'<a class="brandlink" href="#" onclick="{jsgo("menu", "home")}"><b>旅橋</b><i>Tabibashi</i></a>'
HOWTO = {
 "ja": dict(h="使い方", a="このサイトでできること", b="かんたん3ステップ",
            can=("条件や好みから、合うエリアをおすすめ", "地名・スポット名・地図から探す", "天気・ベストシーズン・予算の目安、お気に入りで旅程づくり"),
            how=("行き先の国を選ぶ", "条件を入れて診断、または検索・地図でエリアを選ぶ", "気になるスポットに星を付けて旅程へ")),
 "zh": dict(h="使用方法", a="本網站的功能", b="簡單三步驟",
            can=("依條件與喜好推薦合適的地區", "用地名・景點名・地圖搜尋", "天氣、最佳季節、預算參考，收藏景點安排行程"),
            how=("選擇目的地", "輸入條件診斷，或用搜尋・地圖選擇地區", "替喜歡的景點加星號，安排行程")),
 "en": dict(h="How it works", a="What you can do", b="Three easy steps",
            can=("Get region suggestions that fit your interests", "Search by place, spot or map", "Weather, best season and budget at a glance, plus an itinerary from your favorites"),
            how=("Choose a destination", "Enter your conditions, or search / use the map to pick a region", "Star the spots you like and build your itinerary"))}
def howto_html(lang):
    h = HOWTO[lang]; li = lambda xs, tag: f'<{tag}>' + "".join(f"<li>{x}</li>" for x in xs) + f'</{tag}>'
    return (f'<details class="howto" open><summary>{h["h"]}</summary><div class="hwg"><div><h4>{h["a"]}</h4>{li(h["can"], "ul")}</div><div><h4>{h["b"]}</h4>{li(h["how"], "ol")}</div></div></details>')
def landlang_html(lang): return f'<div class="landbrand"><b>旅橋</b><i>Tabibashi</i><span>{BRAND_TIP[lang]}</span></div><div class="landlang"><span class="lglabel">Languages</span>{langs_html(lang, "")}</div>'
_MI = lambda p: f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{p}</svg>'
MENUICON = {"cond": _MI('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
            "view": _MI('<rect x="3" y="5" width="12" height="9" rx="1"/><path d="M7 18h4M9 14v4"/><rect x="17" y="8" width="4" height="9" rx="1"/>'),
            "other": _MI('<path d="M4 9h14l-3-3M20 15H6l3 3"/>'),
            "fav": _MI('<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z"/>'),
            "prep": _MI('<rect x="5" y="4" width="14" height="17" rx="1.5"/><path d="M9 4v2h6V4M8.5 12l1.8 1.8L14 10M9 17h6"/>'),
            "events": _MI('<rect x="3.5" y="5" width="17" height="15" rx="1.5"/><path d="M3.5 10h17M8 3v4M16 3v4M7.5 13.5h2M11 13.5h2M14.5 13.5h2M7.5 16.5h2M11 16.5h2"/>'),
            "hotels": _MI('<path d="M3 19V6M3 15h18v4M21 15v-3a3 3 0 00-3-3h-7v6"/><circle cx="7" cy="11" r="2"/>'),
            "cars": _MI('<path d="M4 16v-4l2-5h12l2 5v4M3 16h18v2H3zM4 12h16"/><circle cx="7.5" cy="16.5" r="1.5"/><circle cx="16.5" cy="16.5" r="1.5"/>'),
            "trans": _MI('<rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 10h14M9 21l1.5-4M15 21l-1.5-4M8.5 13.5h.01M15.5 13.5h.01"/>')}
MENUX = dict(ja=dict(events="{c}のイベントカレンダー", hotels="{c}のホテルを探す", cars="{c}のレンタカーを探す", trans=transport.T["ja"]["menu"]),
             zh=dict(events="{c}活動行事曆", hotels="搜尋{c}的飯店", cars="搜尋{c}的租車", trans=transport.T["zh"]["menu"]),
             en=dict(events="Events calendar: {c}", hotels="Find hotels in {c}", cars="Find rental cars in {c}", trans=transport.T["en"]["menu"]))
def view_btn(v, lang):
    """ヘッダーの「スマホ表示 / PC表示」切替ボタン（以前はメニュー内にあった）"""
    t = TX("taiwan", lang); txt = t["vp"] if v == "mobile" else t["vm"]
    return f'<a href="#" class="viewbtn" title="{html.escape(txt, quote=True)}" onclick="{jsgo("menu", "view")}">{MENUICON["view"]}<span>{txt}</span></a>'
def menu_html(m, v, lang, nfav=0):
    t = TX(m, lang); c = guide.COUNTRY[lang][m]; X = {k: x.format(c=c) for k, x in MENUX[lang].items()}
    item = lambda k, txt: f'<a href="#" class="mi" onclick="{jsgo("menu", k)}"><span class="mic">{MENUICON[k]}</span><span class="mtx">{txt}</span><span class="mch">›</span></a>'
    return (f'<div class="hm"><div class="hlang"><span class="lglabel">Languages</span>{langs_html(lang, "", short=True)}</div>{view_btn(v, lang)}' + f'<details class="menu"><summary>{t["menu"]}</summary><div class="mlist">{item("cond", t["mcond"])}'
            f'{item("events", X["events"])}{item("hotels", X["hotels"])}{item("cars", X["cars"])}{item("trans", X["trans"])}{item("fav", t["fav_menu"].format(n=nfav))}{item("prep", LBL[lang]["menu_prep"])}{item("other", t["mother"])}'
            f'</div></details></div>')

# 説明文は句点で改行する（brk.kb）。キャッシュする関数は中身を包み直し、結果ごとキャッシュする
def _kbc(fn, size): return functools.lru_cache(maxsize=size)(lambda *a, _f=fn.__wrapped__: kb(_f(*a)))
_region_page = _kbc(_region_page, 256); car_page = _kbc(car_page, 256); hotels_country_page = _kbc(hotels_country_page, 16); cars_country_page = _kbc(cars_country_page, 16); trans_country_page = _kbc(trans_country_page, 16); trans_region_page = _kbc(trans_region_page, 256); search_page = _kbc(search_page, 128)
def _kbf(fn): return functools.wraps(fn)(lambda *a, **k: kb(fn(*a, **k)))
howto_html = _kbf(howto_html); chead_html = _kbf(chead_html); empty_html = _kbf(empty_html)
_recommend = recommend
def recommend(*a, **k): main, side = _recommend(*a, **k); return kb(main), kb(side)
def build_page(m, lang, entry, favs=()):
    st, pl = entry
    if st == "hotel": return kb(hotel_page(m, lang, *pl))
    if pl[0] == "fav": return kb(fav_page(m, lang, favs))
    if pl[0] == "prep": return kb(prep_page(m, lang))
    if pl[0] == "events": return kb(guide.events_page(m, lang))
    if pl[0] == "hotels": return hotels_country_page(m, lang)
    if pl[0] == "cars": return cars_country_page(m, lang)
    if pl[0] == "trans": return trans_country_page(m, lang)
    return region_page(m, lang, pl[1]) if pl[0] == "region" else search_page(m, lang, pl[1])
def region_of(entry):                      # ④⑤ の背景に使うエリア（検索結果は国共通の背景）
    st, pl = entry
    return pl[0] if st == "hotel" else (pl[1] if st == "list" and pl[0] == "region" else None)

# ---------------- ブラウザ設定: 読み込み表示の非表示 + 「戻る」ボタンとの履歴同期 ----------------
HEAD = """<style>footer,.gradio-container footer{display:none !important}.generating,.pending{animation:none !important;border-color:transparent !important}.progress-text,.eta-bar,.progress-level,.progress-level-inner,.wrap.default,.wrap.default.full,.loading,.loader,.toast-wrap{display:none !important}html,body{background:#0b1c1d}</style>
<style>html.tjr .gradio-container{opacity:0 !important}</style>
<script>(function(){var cur=1,ignore=0,inited=false,tm=null;
try{var nv=(performance.getEntriesByType('navigation')[0]||{}).type;window.tjRestore=((nv==='reload'||nv==='back_forward')&&sessionStorage.getItem('tj_state'))?1:0}catch(e){window.tjRestore=0}
if(window.tjRestore){document.documentElement.classList.add('tjr');setTimeout(function(){window.tjRestore=0;document.documentElement.classList.remove('tjr')},9000)}
window.tjNav=function(s){window.tjSpin&&tjSpin(1);var t=document.querySelector('#bridge textarea,#bridge input');if(!t)return;var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t),'value');d.set.call(t,s+'\t'+Date.now());t.dispatchEvent(new Event('input',{bubbles:true}))};
function save(){var e=document.querySelector('#tjstate');if(!e)return;var q=document.querySelector('#tjq'),o={};var key=e.getAttribute('data-s')+'|'+(q?q.getAttribute('data-q'):'');if(key===save.key)return;save.key=key;try{o=JSON.parse(sessionStorage.getItem('tj_state')||'{}')}catch(x){}
 o.s=e.getAttribute('data-s');if(q)o.q=q.getAttribute('data-q');var js=JSON.stringify(o);if(js===save.last)return;save.last=js;try{sessionStorage.setItem('tj_state',js)}catch(x){}}
function depth(){var e=document.querySelector('#navmark');return e?parseInt(e.getAttribute('data-depth')||'1',10):null}
function sync(){var d=depth();if(d===null)return;
 if(window.tjRestore){if(!document.querySelector('#tjstate'))return;window.tjRestore=0;inited=false;document.documentElement.classList.remove('tjr')}
 save();
 if(!inited){history.replaceState({d:d},'');cur=d;inited=true;return}
 if(d>cur){for(var i=cur+1;i<=d;i++)history.pushState({d:i},'');cur=d}
 else if(d<cur){var n=cur-d;cur=d;ignore++;history.go(-n)}
 else{history.replaceState({d:d},'')}}
new MutationObserver(function(){clearTimeout(tm);tm=setTimeout(sync,40)}).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['data-depth']});
window.addEventListener('popstate',function(e){
 if(ignore>0){ignore--;return}
 var d=(e.state&&e.state.d)||1;
 if(d<cur){var n=cur-d;cur=d;for(var i=0;i<n;i++){var b=document.querySelector('#sysback');if(b)b.click()}}
 else if(d>cur){ignore++;history.go(cur-d)}});
document.addEventListener('click',function(e){document.querySelectorAll('details.menu[open]').forEach(function(x){if(!x.contains(e.target))x.removeAttribute('open')})});
})();</script><script>(function(){
var FAV=[];try{FAV=JSON.parse(localStorage.getItem('tj_favs')||'[]')}catch(e){}
function has(r,s){for(var i=0;i<FAV.length;i++){if(FAV[i][0]===r&&FAV[i][1]===s)return i}return -1}
function mark(){var a=document.querySelectorAll('.star');for(var i=0;i<a.length;i++){a[i].classList.toggle('on',has(a[i].dataset.reg,a[i].dataset.sp)>=0)}}
function push(){try{localStorage.setItem('tj_favs',JSON.stringify(FAV))}catch(e){}
 var t=document.querySelector('#bridge2 textarea,#bridge2 input');if(!t)return false;
 var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t),'value');d.set.call(t,JSON.stringify(FAV)+'##'+Date.now());t.dispatchEvent(new Event('input',{bubbles:true}));return true}
window.tjFav=function(b){var i=has(b.dataset.reg,b.dataset.sp);if(i>=0)FAV.splice(i,1);else FAV.push([b.dataset.reg,b.dataset.sp]);mark();push()};
window.tjFavClear=function(){FAV=[];mark();push()};
var tm2=null;new MutationObserver(function(){clearTimeout(tm2);tm2=setTimeout(mark,60)}).observe(document.documentElement,{childList:true,subtree:true});
var tries=0,iv=setInterval(function(){tries++;if(push()||tries>60)clearInterval(iv)},500);
function fb(t){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(a)}
function copyText(t,b){var done=function(){if(b&&b.dataset.ok){var old=b.textContent;b.textContent=b.dataset.ok;setTimeout(function(){b.textContent=old},1800)}};
 if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done,function(){fb(t);done()})}else{fb(t);done()}}
window.tjCopy=function(q,b){copyText(location.origin+location.pathname+q,b)};
window.tjCopyList=function(b){var o=[];document.querySelectorAll('.pg section.cat').forEach(function(s){var h=s.querySelector('h3');o.push('■ '+(h?h.dataset.rg||'':''));s.querySelectorAll('.spot .nm').forEach(function(n){o.push('・'+n.textContent)});o.push('')});copyText(o.join('\\n'),b)};
window.tjFold=function(h,open){var s=h&&h.closest('section');if(!s)return;if(open){s.classList.add('open');s.dataset.auto='';s.scrollIntoView({behavior:'smooth',block:'start'})}else{s.classList.toggle('open');s.dataset.auto=''}};
window.tjGen=function(b){var sec=b.closest('section');if(!sec)return;sec.dataset.g=b.dataset.g;sec.querySelectorAll('.ngb').forEach(function(x){var o=x===b;x.classList.toggle('on',o);x.setAttribute('aria-pressed',o)});
 if(b.closest('.pg')&&b.closest('.pg').querySelector('.f-q'))tjFilter(b);else sec.querySelectorAll('.spot').forEach(function(r){r.classList.toggle('hide',!!b.dataset.g&&r.dataset.g!==b.dataset.g)})};
window.tjFilter=function(el){var pg=el.closest('.pg');if(!pg)return;
 var fnw=pg.querySelector('.f-new'),nw=fnw?(fnw.type==='checkbox'?fnw.checked:fnw.value==='new'):false,off=(pg.querySelector('.f-off')||{}).checked,q=pg.querySelector('.f-q').value.trim().toLowerCase(),mode=pg.querySelector('.f-sort').value,cat=(pg.querySelector('.f-cat')||{}).value||'',shown=0;
 pg.querySelectorAll('section.cat').forEach(function(sec){var box=sec.querySelector('.spots');var rows=[].slice.call(box.querySelectorAll('.spot'));
  rows.sort(function(a,b){if(mode==='name'){return a.dataset.nm<b.dataset.nm?-1:(a.dataset.nm>b.dataset.nm?1:0)}
   if(mode==='off'){var d=(+b.dataset.off)-(+a.dataset.off);if(d)return d}
   return (+a.dataset.i)-(+b.dataset.i)});
  var n=0,gen=sec.dataset.g||'',catok=(!cat||sec.id==='cat-'+cat);rows.forEach(function(r){box.appendChild(r);var ok=catok&&(!gen||r.dataset.g===gen)&&(!off||r.dataset.off==='1')&&(!nw||r.dataset.new==='1')&&(!q||r.dataset.nm.indexOf(q)>=0);r.classList.toggle('hide',!ok);if(ok)n++});
  sec.classList.toggle('hide',!n);if(sec.classList.contains('fold')){if((q||cat||nw)&&n)sec.classList.add('open');else if(!q&&!cat&&!nw&&sec.dataset.auto)sec.classList.remove('open');sec.dataset.auto=(q||cat||nw)?'1':''}var em=sec.querySelector('h3 em');if(em&&em.dataset.t)em.textContent=em.dataset.t.replace('{n}',n);shown+=n});
 var c=pg.querySelector('.f-n');if(c)c.textContent=c.dataset.t.replace('{n}',shown);var z=pg.querySelector('.f-none');if(z)z.classList.toggle('on',shown===0)};
})();</script>"""

HEAD += "<script>" + open(os.path.join(BASE, "plan.js"), encoding="utf-8").read() + "</script>"
guide.R_NAME = rname; guide.NAV = lambda reg: jsgo("region", reg)

def st_mark(m, v, lang, hs):          # 今のページの状態。ブラウザ側で sessionStorage に保存し、更新ボタンのあと on_load で復元する
    return f'<i id="tjstate" hidden data-s="{html.escape(json.dumps(dict(m=m, v=v, l=lang, h=hs), ensure_ascii=False), quote=True)}"></i>'
def slim(comps, vals, sent):
    """差分更新。前回ブラウザへ送った内容と同じものは送り直さない。
    (1) 大きなHTML部品(SLIM)の中身 (2) 表示/非表示・ラベルなどの属性 の両方を部品ごとに記録して比べる。
    入力欄の値(value)は利用者が書き換えるので、SLIM以外では常に送る。"""
    sent = dict(sent or {}); out = []
    for c, x in zip(comps, vals):
        cid = c._id
        if isinstance(x, str):
            if c in SLIM:
                h = hash(x)
                if sent.get(cid) == h: x = gr.update()
                else: sent[cid] = h
        elif isinstance(x, dict) and x.get("__type__") == "update":
            x = dict(x)
            if c in SLIM and isinstance(x.get("value"), str):
                h = hash(x["value"])
                if sent.get(cid) == h: del x["value"]
                else: sent[cid] = h
            props = {k_: v_ for k_, v_ in x.items() if k_ not in ("value", "__type__")}
            if props:
                ph = hash(json.dumps(props, sort_keys=True, default=str, ensure_ascii=False)); pk = "p%s" % cid
                if sent.get(pk) == ph:
                    for k_ in props: del x[k_]
                else: sent[pk] = ph
        out.append(x)
    return out, sent
SLIM = set(); INIT_SENT = {}
# ---------------- UI（landing → cond → result → list / hotel） ----------------
LAND = [("landing", None)]; COND = [("landing", None), ("cond", None)]; START_LANG = "ja"
def ui(m, v, hs, lang, favs=(), reset=True, rebudget=False):
    """画面(hs末尾)・国(m)・表示(v)・言語(lang)に合わせて全コンポーネントを更新する"""
    t = TX(m, lang); st = hs[-1][0]; vis = lambda b: gr.update(visible=b); kw = (lambda x: {"value": x}) if reset else (lambda x: {})
    ca, cb = theme_css(m, v, st == "landing", lang)
    u = {cssA: ca, cssS: stage_css(m, st, lang), cssB: cb, cssM: mobile_css(v), sidecmp: vis(st == "result"),
         style: theme_html(m, v, st, len(hs), region_of(hs[-1]), lang) + st_mark(m, v, lang, hs), landing: vis(st == "landing"), landlang: gr.update(visible=st == "landing", value=landlang_html(lang)), secA: sec_html(lang, 0), secB: sec_html(lang, 1), secC: sec_html(lang, 2), sidemap: gr.update(visible=st == "result", **({"value": map_card(m, lang, v == "mobile")} if st == "result" else {})), howtoc: gr.update(visible=st == "landing", value=howto_html(lang)),
         b_tw: gr.update(value=TX("taiwan", lang)["land"]), b_jp: gr.update(value=TX("japan", lang)["land"]),
         topbar: vis(True), frame: vis(st in ("cond", "result")), tbar: vis(st == "cond"), kwhead: gr.update(visible=st == "cond", value=num_head(lang, 0, m)), catbox: gr.update(visible=st == "cond", **({"value": catsearch_html(m, lang)} if st == "cond" else {})), maphead: num_head(lang, 2, m), p2t: gr.update(visible=st == "cond", value=p2t_html(lang, m)), rescol: vis(st in ("cond", "result")), mapbox: vis(st == "cond"),
         out: gr.update(visible=st == "result", **kw(empty_html(m, lang))), pagecol: vis(st in ("list", "hotel")), maphtml: (map_card(m, lang, v == "mobile") if st == "cond" else gr.update()), menuhtml: menu_html(m, v, lang, len(favs)),
         hb: gr.update(value=t["back"]), hsearch: gr.update(placeholder=t["sph"]), hbtn: gr.update(value=t["sbtn"]), psearch: gr.update(placeholder=t["psph"]), pbtn: gr.update(value=t["sbtn"]),
         chead: num_head(lang, 1, m) if st == "cond" else chead_html(m, lang), days: gr.update(label=t["days"], **kw(4)), budget: gr.update(label=t["budget"], **({"value": t["bval"]} if (reset or rebudget) else {})),
         cur_c: gr.update(visible=lang == "en", label=LBL[lang]["bgt_cur"], **({"value": "USD"} if (reset or rebudget) else {})),
         party: gr.update(label=t["party"], choices=t["party_ch"], **kw("couple")), first: gr.update(label=t["first_lab"], choices=t["first_ch"], info=kn(FIRST_INFO[lang]), **kw("first")),
         acc: gr.update(label=t["more"]), go: gr.update(value=t["btn"]), mk: m, hist: hs, vw: v, lg: lang}
    for c, k in zip(sl, ALL): u[c] = gr.update(label=t["sl"][k], **kw(3))
    if st in ("list", "hotel"): u[pagehtml] = build_page(m, lang, hs[-1], favs)
    return [u.get(c, gr.update()) for c in OUTS]

P2SUB = dict(ja=("行き先は、次の4つの方法で見つけられます。", ["キーワードで見つける", "条件で見つける", "地図で見つける", "カテゴリで見つける"]),
             zh=("您可以用以下4種方式找到目的地。", ["用關鍵字尋找", "用條件尋找", "用地圖尋找", "用分類尋找"]),
             en=("You can find your destination in four ways.", ["Search by keyword", "Choose by conditions", "Explore by map", "Browse by category"]))
NUMD = dict(ja=["スポット名・エリア名・やりたいことを入力して探します。", None, None, "カテゴリを選ぶと、その国で該当するエリアと代表的なスポットを表示します。"],
            zh=["輸入景點名稱、地區或想做的事來搜尋。", None, None, "選擇分類後，會列出該國擁有此分類的地區與代表景點。"],
            en=["Type a spot, a region or what you want to do.", None, None, "Pick a category to see the regions that offer it, with signature spots."])
def num_head(lang, i, m="taiwan"):
    t = TX(m, lang); d = NUMD[lang][i] or (t["condsub"] if i == 1 else t["msub"])
    return f'<div class="numhead"><b>{i + 1}</b><div><h3>{P2SUB[lang][1][i]}</h3><p>{d}</p></div></div>'
KANA = dict(zip(JP_EN, "ほっかいどう あおもり いわて みやぎ あきた やまがた ふくしま いばらき とちぎ ぐんま さいたま ちば とうきょう かながわ にいがた とやま いしかわ ふくい やまなし ながの ぎふ しずおか あいち みえ しが きょうと おおさか ひょうご なら わかやま とっとり しまね おかやま ひろしま やまぐち とくしま かがわ えひめ こうち ふくおか さが ながさき くまもと おおいた みやざき かごしま おきなわ".split()))
KANA.update(dict(zip(TW_EN, "たいぺいし しんぺいし きーるんし たおゆえんし しんちくし しんちくけん びょうりつけん たいちゅうし しょうかけん なんとうけん うんりんけん かぎし かぎけん たいなんし たかおし へいとうけん ぎらんけん かれんけん たいとうけん ほうこけん きんもんけん れんこうけん".split())))
LAT = dict(zip(JP_EN, [43.06, 40.82, 39.70, 38.27, 39.72, 38.24, 37.75, 36.34, 36.57, 36.39, 35.86, 35.61, 35.69, 35.45, 37.90, 36.70, 36.59, 36.07, 35.66, 36.65, 35.39, 34.98, 35.18, 34.73, 35.00, 35.02, 34.69, 34.69, 34.69, 34.23, 35.50, 35.47, 34.66, 34.40, 34.19, 34.07, 34.34, 33.84, 33.56, 33.61, 33.25, 32.74, 32.79, 33.24, 31.91, 31.56, 26.21]))
LAT.update(dict(zip(TW_EN, [25.04, 25.01, 25.13, 24.99, 24.80, 24.70, 24.56, 24.15, 24.07, 23.96, 23.70, 23.48, 23.45, 23.00, 22.63, 22.55, 24.75, 23.98, 22.75, 23.57, 24.43, 26.15])))
def rthumb(reg):
    p = f"images/rt/{reg}.jpg"
    return asset(p) if os.path.exists(os.path.join(BASE, p)) else ""
@functools.lru_cache(maxsize=16)
def catsearch_html(m, lang):
    d = D[m]["spots"].drop_duplicates(["region", "spot"]); present = [c for c in CATS if (d["cat"] == c[0]).any()]
    chips = []; data = {}; regs = set()
    for c in present:
        k = c[0]; img = catbanner_sq(k, m)
        chips.append(f'<button type="button" class="cchip" data-k="{k}" style="--ci:url(\'{img}\')" onclick="tjCat(this)"><span class="cn">{c[1]}<b>{catname(lang, k)}</b></span></button>')
        rows = []
        for reg, gg in d[d["cat"] == k].groupby("region"):
            top = gg.sort_values("tourism_value_score", ascending=False, kind="stable").head(3)
            rows.append([reg, len(gg), [[str(x), en_of(str(x), lang) or ""] for x in top["spot"]]]); regs.add(reg)
        data[k] = rows
    R = {r: [rname(r, lang), KANA.get(r, ""), LAT.get(r, 0), rthumb(r), *FOCUS.get(r, (50, 50))] for r in regs}
    lab = dict(ja=("五十音順", "北から順"), zh=("注音順", "由北至南"), en=("A to Z", "North to South"))[lang]
    blob = html.escape(json.dumps(dict(c=data, r=R, lang=lang), ensure_ascii=False, separators=(",", ":")), quote=True)
    sortbar = f'<div class="csort"><button type="button" class="on" data-s="n" onclick="tjCatSort(this)">{lab[1]}</button><button type="button" data-s="k" onclick="tjCatSort(this)">{lab[0]}</button></div>'
    return f'{num_head(lang, 3, m)}<div class="cchips">{"".join(chips)}</div><div class="cpanels" data-j="{blob}">{sortbar}<div class="cres"></div></div>'
def catbanner_sq(key, m):
    k = f"{key}_{m}" if key in ("shrine", "landmark") else key
    return asset(f"images/catsq/{k}.jpg") if os.path.exists(os.path.join(BASE, "images", "catsq", f"{k}.jpg")) else ""
def p2t_html(lang, m="taiwan"):
    lead, items = P2SUB[lang]; tg = ["kwhead", "formcol", "rescol", "catbox"]
    li = "".join(f'<li><a href="#" class="p2way" onclick="var e=document.getElementById(\'{tg[i - 1]}\');if(e)e.scrollIntoView({{behavior:\'smooth\',block:\'start\'}});return false"><b>{i}</b>{x}</a></li>' for i, x in enumerate(items, 1))
    return f'<div class="p2title"><div class="p2country"><i></i><span>{m.upper()}</span><i></i></div><h1>{TX("taiwan", lang)["p2title"]}</h1><i></i><p class="p2lead">{lead}</p><ol class="p2ways">{li}</ol></div>'
num_head = _kbf(num_head); p2t_html = _kbf(p2t_html)
def pick_tw(v, lang, favs): return ui("taiwan", v, list(COND), lang, favs)
def pick_jp(v, lang, favs): return ui("japan", v, list(COND), lang, favs)
def go_back(m, v, hist, lang, favs): return ui(m, v, hist[:-1] if len(hist) > 1 else hist, lang, favs, reset=False)
def do_search(q, m, v, hist, lang, favs):
    q = (q or "").strip()
    return ui(m, v, hist + [("list", ("search", q))] if q else hist, lang, favs, reset=False)
FAVPAGE = ("list", ("fav", "")); PREPPAGE = ("list", ("prep", ""))
XPAGE = {k: ("list", (k, "")) for k in ("events", "hotels", "cars", "trans")}       # イベントカレンダー / 国全体のホテル・レンタカー
def bridge_in(msg, m, v, hist, lang, favs):        # 結果カード・地図・ホテルボタン・メニュー・言語切替のクリック
    parts = (msg or "").split("\t"); a = parts[0] if parts else ""
    if a == "region" and len(parts) >= 3: m = mkt_of(parts[1]); hist = hist + [("list", ("region", parts[1]))]
    elif a == "hotel" and len(parts) >= 4: m = mkt_of(parts[1]); hist = hist + [("hotel", (parts[1], parts[2]))]
    elif a == "lang" and len(parts) >= 3 and parts[1] in LANGS: return ui(m, v, hist, parts[1], favs, reset=False, rebudget=True)      # 言語を切り替えて同じページを表示（予算欄はその言語の通貨の初期値へ）
    elif a == "menu" and len(parts) >= 3:
        if parts[1] == "home": return ui(m, v, list(LAND), lang, favs)                                       # サイト名クリック: トップページへ
        if parts[1] == "cond": return ui(m, v, list(COND), lang, favs, reset=False)                         # 日本（台湾）の行き先を探す（2ページ目）
        if parts[1] == "view": return ui(m, "mobile" if v == "pc" else "pc", hist, lang, favs, reset=False)  # スマホ表示 <-> PC表示
        if parts[1] == "other": return ui(OTHER[m], v, list(COND), lang, favs)                                 # もう一方の国の2ページ目へ
        if parts[1] == "prep": return ui(m, v, hist if hist[-1] == PREPPAGE else hist + [PREPPAGE], lang, favs, reset=False)
        if parts[1] in XPAGE: pg = XPAGE[parts[1]]; return ui(m, v, hist if hist[-1] == pg else hist + [pg], lang, favs, reset=False)
        if parts[1] == "fav": return ui(m, v, hist if hist[-1] == FAVPAGE else hist + [FAVPAGE], lang, favs, reset=False)   # お気に入り・旅程
    return ui(m, v, hist, lang, favs, reset=False)
def set_favs(msg, m, v, hist, lang, favs):           # ブラウザ側(localStorage)のお気に入りをサーバー側の状態へ反映
    try: raw = json.loads((msg or "[]").rsplit("##", 1)[0])
    except Exception: raw = favs
    new = []
    for x in raw if isinstance(raw, list) else []:
        if isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) for y in x) and x[0] in ALLREG and x not in new: new.append(x)
    new = new[:300]
    if new == favs: return favs, gr.update(), gr.update()        # 変化なし（起動直後の同期など）は画面を再描画しない
    page = build_page(m, lang, hist[-1], new) if hist[-1] == FAVPAGE else gr.update()
    return new, menu_html(m, v, lang, len(new)), page
def diagnose(m, v, hist, lang, favs, sent, days, budget, cur, party, first, *scores):          # ② → ③ 結果画面へ遷移
    st = hist[-1][0]; h2 = hist + [("result", None)] if st == "cond" else hist
    page = theme_html(m, v, "result", len(h2), None, lang) + st_mark(m, v, lang, h2) if st != "result" else gr.update()   # 結果画面での再診断は背景を再描画しない
    main, side = recommend(m, lang, days, budget, party, first, *scores, v=v, cur=cur)
    vals = [page, stage_css(m, "result", lang), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True, value=main), h2, gr.update(visible=False),
            gr.update(visible=True, value=map_card(m, lang, v == "mobile")), gr.update(visible=False), gr.update(visible=False), chead_html(m, lang), gr.update(visible=True, value=side)]
    vals, sent = slim(DIAG_OUTS, vals, sent)
    return vals + [sent]
def parse_q(q):
    """共有リンク / 復元用の診断条件(?m=..&d=..)を読む。不正なら None"""
    try:
        m = q["m"]; assert m in ("taiwan", "japan")
        days = min(10, max(1, int(q["d"]))); budget = min(10_000_000, max(0, int(q["b"]))); party = q["p"]; assert party in [p[0] for p in PARTY]
        first = bool(int(q["f"])); sc = [min(5, max(1, int(x))) for x in q["s"].split(",")]; assert len(sc) == len(ALL)
        return dict(m=m, days=days, budget=budget, party=party, first=first, sc=sc, cur=q.get("c") if q.get("c") in ("USD", "EUR") else "USD")
    except Exception: return None
def clean_hist(h, m):
    """ブラウザから戻ってきた履歴を検証する(想定した形・実在するエリアだけを通す)"""
    out = [("landing", None)]
    for e in (h or [])[1:20]:
        st, pl = (e + [None, None])[:2] if isinstance(e, list) else (None, None)
        if st in ("cond", "result") and pl is None: out.append((st, None))
        elif st == "list" and isinstance(pl, list) and len(pl) == 2 and all(isinstance(x, str) for x in pl):
            if pl[0] == "region" and pl[1] in ALLREG: out.append(("list", ("region", pl[1])))
            elif pl[0] == "search": out.append(("list", ("search", pl[1][:80])))
            elif pl[0] in ("fav", "prep", "events", "hotels", "cars", "trans"): out.append(("list", (pl[0], "")))
            else: break
        elif st == "hotel" and isinstance(pl, list) and len(pl) == 2 and all(isinstance(x, str) for x in pl) and pl[0] in ALLREG: out.append(("hotel", (pl[0], pl[1][:120])))
        else: break
    return out
def detect_env(request):
    """ブラウザの第1言語（ja→日本語 / zh→中国語 / その他→英語）と端末（スマホ→mobile / その他→pc）を判定"""
    h = getattr(request, "headers", None) or {}
    first = (h.get("accept-language") or "").split(",")[0].split(";")[0].strip().lower()
    lang = "ja" if first.startswith("ja") else "zh" if first.startswith("zh") else "en"
    ua = h.get("user-agent") or ""
    return lang, ("mobile" if re.search(r"Mobi|iPhone|iPod", ua) else "pc")
def on_load(raw, sent, request: gr.Request):
    """最初の表示。(1) 更新ボタン: 直前のページを復元 (2) 共有リンク(?m=..&d=..): その条件の診断結果 (3) それ以外: ブラウザの言語・端末に合わせたトップ"""
    dlang, dview = detect_env(request); hs = None; P = None; sent = dict(INIT_SENT)      # 読み込み直後のブラウザは初期表示の内容を持っている
    try:
        o = json.loads(raw) if raw else None
        if o:
            s = json.loads(o["s"]); m = s["m"]; v = s["v"]; lang = s["l"]; assert m in ("taiwan", "japan") and v in ("pc", "mobile") and lang in LANGS
            hs = clean_hist(s["h"], m); P = parse_q(dict(x.split("=", 1) for x in unquote(str(o.get("q") or "")).lstrip("?").split("&") if "=" in x))
            if any(e[0] == "result" for e in hs) and (P is None or P["m"] != m): hs = list(COND)       # 診断条件が残っていなければ条件ページへ
    except Exception: hs = None
    if hs is None:
        q = dict(request.query_params) if request is not None else {}
        P = parse_q(q)
        if P is None:
            if dlang == "ja" and dview == "pc" and not raw: return [gr.update() for _ in OUTS] + [sent]
            u, sent = slim(OUTS, ui(START, dview, list(LAND), dlang, [], reset=True), sent); return u + [sent]
        m = P["m"]; lang = q.get("l", dlang); lang = lang if lang in LANGS else dlang; v = q.get("v", dview); v = v if v in ("pc", "mobile") else dview
        hs = list(COND) + [("result", None)]
    u = ui(m, v, hs, lang, [], reset=True)
    def setv(c, **kw): i = OUTS.index(c); u[i] = {**(u[i] if isinstance(u[i], dict) else gr.update(value=u[i])), **kw}
    if P and any(e[0] == "result" for e in hs):
        setv(days_c, value=P["days"]); setv(budget_c, value=P["budget"]); setv(party_c, value=P["party"]); setv(first_c, value="first" if P["first"] else "repeat")
        for c, x in zip(sl, P["sc"]): setv(c, value=x)
        setv(cur_cc, value=P["cur"])
        main, side = recommend(m, lang, P["days"], P["budget"], P["party"], P["first"], *P["sc"], v=v, cur=P["cur"])
        setv(out, value=main); setv(sidecmp, value=side)
    u, sent = slim(OUTS, u, sent)
    return u + [sent]


# ---------------- 天気（サーバー経由の予備経路） ----------------
# ブラウザから Open-Meteo へ直接つながらない・遅いときに使う。Hugging Face Spaces などの共有サーバーは、他のアプリと
# 同じ送信元IPから Open-Meteo を呼ぶため、IP単位の利用上限（429）に当たりやすい。そこで
#  1) 全エリアの代表地点（geo.LL、69地点）を「1回のリクエスト」でまとめて取得し、30分間キャッシュする（閲覧数によらず30分に1回）
#  2) 取得に失敗・429 のときは5分間は外部へ問い合わせない（連続失敗で上限を悪化させない）
#  3) 新しいデータが取れないときは、6時間以内の古いデータを返す（JSON の "_t" に取得時刻。画面に「○時○分時点」と表示）
from geo import LL as _LL
_WX = {}                                                    # (lat, lon) -> (取得時刻, JSON文字列)
_WXS = dict(t=0.0, busy=False, hold=0.0)                    # まとめ取得の時刻 / 実行中 / この時刻まで外部へ問い合わせない
_WX_FRESH, _WX_STALE, _WX_HOLD = 1800, 6 * 3600, 300
_WXQ = ("current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=14")
_WXFAKE = '{"current":{"temperature_2m":24.1,"relative_humidity_2m":60,"weather_code":2,"wind_speed_10m":9.0},"daily":{"time":["2026-11-13","2026-11-14"],"weather_code":[2,61],"temperature_2m_max":[25,22],"temperature_2m_min":[18,16],"precipitation_probability_max":[10,60]}}'
def _wx_key(lat, lon): return (round(float(lat), 2), round(float(lon), 2))
def _wx_ok(d): return isinstance(d, dict) and isinstance(d.get("current"), dict) and isinstance(d.get("daily"), dict) and d["daily"].get("time")
def _wx_get(keys, timeout):
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&" % (",".join(str(k[0]) for k in keys), ",".join(str(k[1]) for k in keys))) + _WXQ
    req = urllib.request.Request(url, headers={"User-Agent": "Tabibashi-travel-guide/1.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    return d if isinstance(d, list) else [d]
def _wx_put(k, d, now): d = dict(d, _t=int(now)); txt = json.dumps(d, separators=(",", ":")); _WX[k] = (now, txt); return txt
def _wx_fail(e):
    _WXS["hold"] = _time.time() + _WX_HOLD
    print("wx:", getattr(e, "code", ""), type(e).__name__, str(e)[:120])
def _wx_batch():
    keys = sorted({_wx_key(*v) for v in _LL.values()})
    try:
        now = _time.time()
        for k, d in zip(keys, _wx_get(keys, 25)):
            if _wx_ok(d): _wx_put(k, d, now)
    except Exception as e: _wx_fail(e)
    finally: _WXS["busy"] = False
def wx_prefetch():
    """全エリアをまとめて取得（前回から30分以上たっていて、待機中でなければ。裏のスレッドで実行）"""
    now = _time.time()
    if os.environ.get("WX_FAKE") or _WXS["busy"] or now - _WXS["t"] < _WX_FRESH - 120 or now < _WXS["hold"]: return
    _WXS.update(busy=True, t=now); threading.Thread(target=_wx_batch, daemon=True).start()
def wx_api(lat: float, lon: float) -> str:
    """天気: ブラウザから直接取得できない環境向けに、サーバー経由で Open-Meteo の予報を返す（JSON文字列）。"""
    if os.environ.get("WX_FAKE"): return _WXFAKE
    k = _wx_key(lat, lon); now = _time.time(); hit = _WX.get(k)
    wx_prefetch()
    if hit and now - hit[0] < _WX_FRESH: return hit[1]
    if now >= _WXS["hold"]:                                   # キャッシュにない・古い地点は、その地点だけ取得（最大2回）
        for i in range(2):
            try:
                d = _wx_get([k], 7)[0]
                if _wx_ok(d): return _wx_put(k, d, _time.time())
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500: _wx_fail(e); break
            except Exception as e:
                if i: _wx_fail(e)
                else: _time.sleep(0.5)
    if hit and now - hit[0] < _WX_STALE: return hit[1]        # 新しく取れないときは、6時間以内の古いデータ
    raise gr.Error("weather unavailable")
with gr.Blocks(title="Taiwan | Japan Journey") as demo:
    mk = gr.State(START); vw = gr.State("pc"); hist = gr.State(list(LAND)); lg = gr.State(START_LANG); fv = gr.State([]); t0 = TX(START, START_LANG)
    with gr.Row(elem_id="topbar") as topbar:                       # 固定ヘッダー: 戻る / 検索 / メニュー
        brand = gr.HTML(brand_html(START_LANG), elem_id="brand")
        hb = gr.Button(t0["back"], elem_id="home")
        with gr.Row(elem_id="hsearch"):
            hsearch = gr.Textbox(show_label=False, container=False, placeholder=t0["sph"], lines=1, max_lines=1, scale=5)
            hbtn = gr.Button(t0["sbtn"], elem_id="hbtn", scale=1)
        menuhtml = gr.HTML(menu_html(START, "pc", START_LANG), elem_id="menuhtml")
    _ca, _cb = theme_css(START, "pc", True, START_LANG)
    cssA = gr.HTML(_ca, elem_classes="hidden-bridge"); cssS = gr.HTML(stage_css(START, "landing", START_LANG), elem_classes="hidden-bridge"); cssB = gr.HTML(_cb, elem_classes="hidden-bridge"); cssM = gr.HTML("", elem_classes="hidden-bridge")
    style = gr.HTML(theme_html(START, "pc", "landing", 1, None, START_LANG))
    snt = gr.State({}); stin = gr.Textbox(elem_classes="hidden-bridge", show_label=False)
    landlang = gr.HTML(landlang_html(START_LANG), elem_id="landlang")
    with gr.Row(elem_id="landing") as landing:
        b_tw = gr.Button(TX("taiwan", START_LANG)["land"], elem_id="pick-tw")
        b_jp = gr.Button(TX("japan", START_LANG)["land"], elem_id="pick-jp")
    howtoc = gr.HTML(howto_html(START_LANG), elem_id="howtoc")
    p2t = gr.HTML(p2t_html(START_LANG), elem_id="p2t", visible=False)
    with gr.Column(elem_id="frame", visible=False) as frame:                      # ② 全体を1つの枠で囲み、「T」の字で区切る
        kwhead = gr.HTML(num_head(START_LANG, 0, START), elem_id="kwhead", visible=False)
        with gr.Row(elem_id="tbar", visible=False) as tbar:                       #   T の上: 検索バー + 検索ボタン
            psearch = gr.Textbox(show_label=False, container=False, placeholder=t0["psph"], lines=1, max_lines=1, scale=6)
            pbtn = gr.Button(t0["sbtn"], elem_id="pbtn", scale=1)
        with gr.Row(equal_height=False, elem_id="main"):
            with gr.Column(scale=4, elem_classes="panel", elem_id="formcol"):     #   T の左下: 旅の条件 + 診断ボタン
                sidemap = gr.HTML(map_card(START, START_LANG), visible=False, elem_id="sidemap")
                with gr.Column(elem_id="condbox"):
                    chead = gr.HTML(num_head(START_LANG, 1, START))
                    secA = gr.HTML(sec_html(START_LANG, 0), elem_classes="fsec")
                    days = gr.Slider(1, 10, 4, step=1, label=t0["days"])
                    party = gr.Dropdown(t0["party_ch"], value="couple", label=t0["party"], interactive=True, elem_id="partyd")
                    first = gr.Radio(t0["first_ch"], value="first", label=t0["first_lab"], info=kn(FIRST_INFO[START_LANG]), elem_id="firstr")
                    secB = gr.HTML(sec_html(START_LANG, 1), elem_classes="fsec")
                    budget = gr.Number(t0["bval"], label=t0["budget"])
                    cur_c = gr.Dropdown([("USD ($)", "USD"), ("EUR (€)", "EUR")], value="USD", label=LBL[START_LANG]["bgt_cur"], visible=START_LANG == "en", elem_id="curc")
                    secC = gr.HTML(sec_html(START_LANG, 2), elem_classes="fsec")
                    sl = [gr.Slider(1, 5, 3, step=1, label=t0["sl"][k]) for k in CORE]
                    with gr.Accordion(t0["more"], open=False) as acc:
                        sl += [gr.Slider(1, 5, 3, step=1, label=t0["sl"][k]) for k in ALL[len(CORE):]]
                    go = gr.Button(t0["btn"], variant="primary", size="lg", elem_id="go")
                sidecmp = gr.HTML("", visible=False, elem_id="sidecmp")              # 結果画面: 上位3エリアの比較 + 地方ブロック別の相性
            with gr.Column(scale=9, elem_id="rescol") as rescol:                  #   T の右下: 地図（結果画面では結果カード）
                with gr.Column(visible=False) as mapbox:
                    maphead = gr.HTML(num_head(START_LANG, 2, START), elem_id="maphead")
                    maphtml = gr.HTML(map_card(START, START_LANG))
                out = gr.HTML(empty_html(START, START_LANG), visible=False)
        catbox = gr.HTML(catsearch_html(START, START_LANG), elem_id="catbox", visible=False)
    with gr.Column(elem_id="pagecol", visible=False) as pagecol:
        pagehtml = gr.HTML("")
    bridge = gr.Textbox(elem_id="bridge", elem_classes="hidden-bridge", show_label=False)
    bridge2 = gr.Textbox(elem_id="bridge2", elem_classes="hidden-bridge", show_label=False)      # お気に入り(localStorage)との同期用
    sysback = gr.Button("back", elem_id="sysback", elem_classes="hidden-bridge")        # ブラウザの「戻る」用
    OUTS = [cssA, cssS, cssB, cssM, sidecmp, style, landing, landlang, howtoc, secA, secB, secC, sidemap, kwhead, catbox, maphead, b_tw, b_jp, topbar, p2t, frame, tbar, rescol, mapbox, out, pagecol, pagehtml, maphtml, menuhtml, hb, hsearch, hbtn, psearch, pbtn, chead,
            days, budget, cur_c, party, first, *sl, acc, go, mk, hist, vw, lg]
    days_c, budget_c, party_c, first_c, cur_cc = days, budget, party, first, cur_c
    SP = dict(show_progress="hidden", queue=QUEUE)                                                    # 読み込み表示（オレンジのマーク）を出さない
    SLIM.update({cssA, cssS, cssB, cssM, style, sidemap, catbox, maphtml, kwhead, maphead, p2t, chead, secA, secB, secC, howtoc, landlang})
    SPOFF = "() => { window.tjSpin && tjSpin(0); }"                                      # ページ遷移が終わったら、ぐるぐるマークを消す
    def W(fn):                                                                           # 差分更新: 前回と同じ部品は送り直さない
        def g(*args):
            u, sent = slim(OUTS, fn(*args[:-1]), args[-1]); return u + [sent]
        return g
    INIT_SENT.update({c._id: hash(c.value) for c in SLIM if isinstance(getattr(c, "value", None), str)})
    OS = OUTS + [snt]; _off = lambda ev: ev.then(None, None, None, js=SPOFF)
    _off(b_tw.click(W(pick_tw), [vw, lg, fv, snt], OS, **SP)); _off(b_jp.click(W(pick_jp), [vw, lg, fv, snt], OS, **SP))
    S4 = [mk, vw, hist, lg, fv]; S5 = S4 + [snt]
    _off(hb.click(W(go_back), S5, OS, **SP)); _off(sysback.click(W(go_back), S5, OS, **SP))
    for box, btn in ((hsearch, hbtn), (psearch, pbtn)):
        _off(box.submit(W(do_search), [box, *S5], OS, **SP)); _off(btn.click(W(do_search), [box, *S5], OS, **SP))
    bridge.change(W(bridge_in), [bridge, *S5], OS, **SP).then(None, None, None, js="() => { window.tjSpin && tjSpin(0); const b = document.querySelector('#bridge textarea, #bridge input'); if (!b || !/^\\s*\"?lang/.test(b.value)) window.scrollTo({top: 0}); }")
    bridge2.change(set_favs, [bridge2, *S4], [fv, menuhtml, pagehtml], **SP)
    demo.load(on_load, [stin, snt], OS, js="() => { let s = ''; try { if (window.tjRestore) s = sessionStorage.getItem('tj_state') || ''; } catch (e) {} if (!s) { window.tjRestore = 0; document.documentElement.classList.remove('tjr'); } return [s, {}]; }", **SP)
    gr.api(wx_api, api_name="wx", queue=False, concurrency_limit=None)        # 天気の予備経路（待ち行列を通さず、同時に何件でも）
    def cur_switch(amount, new):
        old = "EUR" if new == "USD" else "USD"
        try: return nice(conv(amount or 0, old, new), new)
        except Exception: return gr.update()
    cur_c.input(cur_switch, [budget, cur_c], budget, **SP)
    DIAG_OUTS = [style, cssS, tbar, mapbox, out, hist, p2t, sidemap, kwhead, catbox, chead, sidecmp]
    go.click(diagnose, [*S5, days, budget, cur_c, party, first, *sl], DIAG_OUTS + [snt], **SP).then(None, None, None, js="() => { window.tjSpin && tjSpin(0); window.scrollTo({top: 0}); }")

def _prewarm():
    """起動直後に裏で、地図・カテゴリ一覧・全エリアページ・レンタカーページを作ってキャッシュに入れる（初回表示の待ち時間をなくす）"""
    wx_prefetch()                                            # 天気: 全エリアの予報を先に取得しておく（サーバー経由の予備経路用）
    try:
        for lang in LANGS:
            for m in ("taiwan", "japan"):
                catsearch_html(m, lang); map_card(m, lang, False); map_card(m, lang, True)
        for m in ("taiwan", "japan"): _spot_rec(m, "", "")
        for lang in LANGS:
            for m in ("taiwan", "japan"):
                for reg in sorted(set(D[m]["spots"].region)):
                    region_page(m, lang, reg); car_page(m, lang, reg); trans_region_page(m, lang, reg); _time.sleep(0.01)
    except Exception as e: print("prewarm:", e)
threading.Thread(target=_prewarm, daemon=True).start()

if __name__ == "__main__":
    # run_history=False: Gradio 6 の「実行履歴」は、画面遷移のたびに全出力(1MB超)をブラウザの localStorage に書き直すため、遷移が遅くなる
    demo.launch(server_name="0.0.0.0", server_port=(int(os.environ["PORT"]) if os.environ.get("PORT") else None), head=HEAD, run_history=False)
