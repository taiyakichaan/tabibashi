"""Python版（元の app.py）で推薦を実行し、JS版と照合するための「正解データ」を作る。
使い方: python tools/make_golden.py <元アプリのフォルダ> <出力 json> [1市場あたりのケース数=400]

各ケースについて
  1) app.py の recommend() と同じ式で、数値（確率・寄与度・スポットのスコア）を構造化して記録する
  2) 実際の recommend() が返す HTML から 地域の順位・一致度%・理由の+pt・スポット順・ブロック別% を読み取り、
     1) と食い違いがないかを確かめる（＝この正解データが本物の app.py の出力と同じであることの保証）
前提: app.py の recommend() の並べ替えに kind="stable" を指定した版（tools/app_stable_sort.patch 適用済み）を使う。
未適用の app.py では、同点スポットの順番が numpy の不安定ソート任せになり、環境によって変わりうる。
未適用の版を渡した場合は「HTMLとの不一致」として検出される。
"""
import html as H, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from load_app import load

LANGS = ["ja", "zh", "en"]


def gen_cases(a, m, n, seed):
    import fx
    rnd = random.Random(seed)
    cases = []
    def add(lang, days, budget, party, first, scores, cur="USD"):
        cases.append(dict(m=m, lang=lang, days=days, budget=budget, cur=cur, party=party, first=first, scores=scores))
    nS = len(a.ALL)
    for lang in LANGS:                                    # 境界のケース
        cu = fx.cur_of(lang, "USD")
        dflt = fx.default_budget(m, cu)
        add(lang, 4, dflt, "friends", "first", [3] * nS)
        add(lang, 1, 0, "solo", "repeat", [1] * nS)
        add(lang, 10, dflt * 20, "family", "first", [5] * nS)
        add(lang, 7, dflt, "couple", "repeat", [5 if i % 2 else 1 for i in range(nS)])
    add("en", 3, 120, "couple", "first", [3] * nS, cur="EUR")
    for _ in range(n):
        lang = rnd.choice(LANGS); cur = rnd.choice(["USD", "EUR"]) if lang == "en" else "USD"
        cu = fx.cur_of(lang, cur); step = fx.STEP[cu]; dflt = fx.default_budget(m, cu)
        budget = max(0, int(round(dflt * rnd.choice([0.3, 0.5, 0.8, 1, 1.5, 2, 3, 5]) * rnd.uniform(0.7, 1.3) / step)) * step)
        add(lang, rnd.randint(1, 10), budget, rnd.choice([k for k, _ in a.PARTY]), rnd.choice(["first", "repeat"]),
            [rnd.randint(1, 5) for _ in range(nS)], cur=cur)
    return cases


def core(a, c):
    """recommend() の数値部分を、同じ式・同じ順番で計算する（HTML は作らない）"""
    import numpy as np, pandas as pd
    from fx import BASE as FXB, conv, cur_of
    m, d = c["m"], a.D[c["m"]]
    first = c["first"] in (True, "first", 1); cu = cur_of(c["lang"], c["cur"])
    vals = dict(zip(a.ALL, c["scores"]))
    row = {"trip_days": c["days"], "budget_per_day": np.log1p(conv(c["budget"] or 0, cu, FXB[m])), "party_type": c["party"], "first_visit": int(first)}
    for k, val in vals.items(): row[a.KEYS.get(k, f"{k}_interest")] = val
    feats = d["feats"]; X = pd.DataFrame([row])[feats]; classes = list(d["model"].classes_)
    pv_raw = d["model"].predict_proba(X)[0]; pv = pv_raw
    if first: pv = pv * (1 + a.FIRST_W * np.array([a.POP[m].get(k, 0.0) for k in classes])); pv = pv / pv.sum()
    p = pd.Series(pv, index=classes).sort_values(ascending=False)
    alt = []
    for f in feats: r2 = dict(row); r2[f] = d["base"][f]; alt.append(r2)
    delta = pv[None, :] - d["model"].predict_proba(pd.DataFrame(alt)[feats])
    pref = np.array([vals[k] for k in a.SPOT_COLS])
    regions, ties = [], 0
    for reg, pr in p.head(5).items():
        allr = d["spots"][d["spots"].region == reg].drop_duplicates("spot")
        s = allr.copy(); s["match"] = s[a.SPOT_COLS].to_numpy() @ pref + s["tourism_value_score"].fillna(0).to_numpy() / 100
        st = s.sort_values("match", ascending=False, kind="stable").head(5)                       # 同点は CSV の行順
        if s["match"].duplicated().any(): ties += 1
        cc = delta[:, classes.index(reg)]; top = [int(j) for j in np.argsort(-cc, kind="stable")[:3] if cc[j] > 0.002]
        regions.append(dict(region=reg, prob=float(pr), pct=f"{pr:.0%}", n_spots=int(len(allr)),
                            spots=[dict(spot=str(r["spot"]), match=float(r["match"])) for _, r in st.iterrows()],
                                                        why=[dict(feat=feats[j], delta=float(cc[j]), pt=f"+{cc[j] * 100:.1f}pt") for j in top]))
    blk = p.groupby(p.index.map(a.BLOCKS[m])).sum().sort_values(ascending=False)
    return dict(
        x=dict(budget_log=float(row["budget_per_day"]), first=first, cur=cu),
        proba_model=[float(v) for v in pv_raw],                     # モデルそのものの確率（classes 順）
        proba=[float(v) for v in pv],                               # 「初めて」補正後（classes 順）
        ranking=list(p.index), top5=regions,
        blocks=[dict(block=k, value=float(v), pct=f"{v:.0%}", width=f"{v / blk.max() * 100:.0f}") for k, v in blk.items()],
    ), ties


RW = re.compile(r'<div class="rw">(.*?)<div class="more">', re.S)
def parse_html(h, side):
    out = []
    for blk in RW.findall(h):
        reg = H.unescape(re.search(r'tjNav\(&quot;region\\t(.*?)&quot;\)', blk).group(1))
        pct = re.search(r'<div class="pct">(\d+%)', blk).group(1)
        why = re.findall(r'<b>(\+[\d.]+pt)</b>', blk)
        spots = [H.unescape(x) for x in re.findall(r'class="star" data-reg="[^"]*" data-sp="([^"]*)"', blk)]
        out.append(dict(region=reg, pct=pct, why=why, spots=spots))
    bars = re.findall(r'<div class="bar"><span class="l">.*?</span><span class="t"><span class="f" style="width:(\d+)%"></span></span><span class="v">(\d+%)</span>', side)
    return out, bars


def main(app_dir, out_path, n):
    out_path = os.path.abspath(out_path)
    a = load(app_dir)
    import inspect
    if 'kind="stable"' not in inspect.getsource(getattr(a, "_recommend", a.recommend)): print("注意: app.py に tools/app_stable_sort.patch が当たっていません")
    allc, bad, ties_total, tie_cases = [], [], 0, 0
    for mi, m in enumerate(("taiwan", "japan")):
        for c in gen_cases(a, m, n, seed=100 + mi):
            exp, ties = core(a, c)
            h, side = a.recommend(c["m"], c["lang"], c["days"], c["budget"], c["party"], c["first"], *c["scores"], cur=c["cur"])
            got, bars = parse_html(h, side)
            # 1) と 2) の照合
            mine = [dict(region=r["region"], pct=r["pct"], why=[w["pt"] for w in r["why"]], spots=[x["spot"] for x in r["spots"]]) for r in exp["top5"]]
            if mine != got or [(b["width"], b["pct"]) for b in exp["blocks"]] != bars:
                bad.append(dict(case=c, mine=mine, html=got))
            ties_total += ties; tie_cases += bool(ties)
            allc.append(dict(input=c, expected=exp))
    import fx                                              # 金額の丸め・表記（Python の round は偶数丸め）
    fxc = []
    rnd = random.Random(7)
    vals = [0, 0.5, 1.5, 2.5, 49.5, 50, 150, 250, 1250, 2500, 12345.5] + [round(rnd.uniform(0, 200000), rnd.choice([0, 1, 2])) for _ in range(300)]
    for x in vals:
        for a_ in fx.STEP:
            for b_ in fx.STEP:
                y = fx.conv(x, a_, b_)
                fxc.append(dict(x=x, a=a_, b=b_, conv=y, nice=fx.nice(y, b_), fmt=fx.fmt(y, b_)))
    dflt = {m: {c: fx.default_budget(m, c) for c in fx.STEP} for m in fx.BASE}
    json.dump(dict(app="travel_app_20261117_v19", cases=allc, fx=fxc, default_budget=dflt), open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"cases={len(allc)}  HTMLとの不一致={len(bad)}  同点スポットを含むケース={tie_cases}（地域カード{ties_total}枚）")
    if bad: print(json.dumps(bad[:2], ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 400)
