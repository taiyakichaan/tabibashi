"""スマホ用の地図（map_card(..., big=True)）の地名ラベルを置き直す。
使い方: python tools/map_labels.py <site フォルダ>      （site/data/ui_<言語>.json の m[国].map.mobile を書き換える）

元の配置は、地図の外に出す地名を左右の端に縦に詰めて並べる方式。スマホでは文字が大きい（1.75倍）ため並びきらず、
遠くへ押し出されて引き出し線が長く交差していた。ここでは地名ごとに、指す点の周りに置き場所の候補を作り、
  ・文字どうしが重ならない／引き出し線どうしが交差しない／線が他の地名をまたがない（守る条件）
  ・指す点から近い／陸地（他の地域）にかからない／地図の幅を広げすぎない（なるべく）
を満たす組み合わせを探す。元アプリがなくても、書き出し済みの SVG だけから組み直せる。
地図の中に収まっている地名（エリアの上に直接書かれているもの）はそのまま。
"""
import json, math, os, re, sys

import numpy as np
from PIL import Image, ImageDraw

NUM = r"-?\d+(?:\.\d+)?"


def tw(s, fs):                                   # app.py map_card と同じ概算幅
    return sum(fs if ord(ch) > 255 else fs * .56 for ch in s)


def rings(d):
    out = []
    for sub in re.findall(r"M[^MZ]*Z?", d):
        v = [float(x) for x in re.findall(NUM, sub)]
        if len(v) >= 6: out.append(list(zip(v[0::2], v[1::2])))
    return out


def seg_x(p1, p2, p3, p4):                       # 線分の交差（端点の接触は除く）
    def o(a, b, c): return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def seg_box(p, q, b, pad=1.5):                   # 線分（両端を少し除く）が箱（x0,y0,x1,y1）を通るか（Liang–Barsky）
    x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
    dx, dy = q[0] - p[0], q[1] - p[1]; t0, t1 = 0.04, 0.96
    for pp, qq in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pp == 0:
            if qq < 0: return False
        else:
            t = qq / pp
            if pp < 0: t0 = max(t0, t)
            else: t1 = min(t1, t)
            if t0 > t1: return False
    return True


def box_ov(a, b, pad=2.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def relayout(svg):
    vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    H = vb[3]
    regs = re.findall(r'<g class="pf"[^>]*><title>([^<]*)</title><path d="([^"]+)"', svg)        # 地域ごとの輪郭（地域名つき）
    land = [r for _, d in regs for r in rings(d)]
    allx = [p[0] for r in land for p in r]; minx, maxx = min(allx), max(allx)
    ins = re.search(rf'<rect class="inset" x="({NUM})" y="({NUM})" width="({NUM})" height="({NUM})"/>', svg)
    inset = [float(ins.group(i)) for i in range(1, 5)] if ins else None
    # 陸地の塗り（1px = 0.5 単位）と、その累積和（箱の中の陸地の割合をすぐ求める）
    S = 2.0; ox = min(minx, vb[0]) - 260; Wpx = int((max(maxx, vb[0] + vb[2]) + 260 - ox) * S); Hpx = int(H * S) + 2
    img = Image.new("L", (Wpx, Hpx), 0); dr = ImageDraw.Draw(img)            # 画素の値 = 地域の番号（1〜）。0 は海
    rid = {}
    for k, (name, d) in enumerate(regs, 1):
        rid[name] = k
        for r in rings(d): dr.polygon([((x - ox) * S, y * S) for x, y in r], fill=k)
    if inset: dr.rectangle([(inset[0] - ox) * S, inset[1] * S, (inset[0] + inset[2] - ox) * S, (inset[1] + inset[3]) * S], outline=255, width=3)
    A = np.asarray(img)
    SAT = (A > 0).astype(np.float32).cumsum(0).cumsum(1)
    def rect(b):
        x0, y0, x1, y1 = [int(round(v)) for v in ((b[0] - ox) * S, b[1] * S, (b[2] - ox) * S, b[3] * S)]
        return max(0, x0), max(0, y0), min(Wpx - 1, x1), min(Hpx - 1, y1)
    def land_frac(b, own=None):                  # 箱の中の陸地の割合（自分の地域の上は軽く数える）
        x0, y0, x1, y1 = rect(b)
        if x1 <= x0 or y1 <= y0: return 0.0
        tot = SAT[y1, x1] - SAT[y0 - 1, x1] * (y0 > 0) - SAT[y1, x0 - 1] * (x0 > 0) + SAT[y0 - 1, x0 - 1] * (x0 > 0 and y0 > 0)
        area = (x1 - x0) * (y1 - y0); frac = float(tot) / area
        if own is None or own not in rid: return frac
        mine = float((A[y0:y1, x0:x1] == rid[own]).sum()) / area
        return frac - 0.85 * mine

    # 地図の中の地名（動かさない）
    inner = []; inner_m = []
    for m in re.finditer(rf'<text class="lb al" x="({NUM})" y="({NUM})" font-size="({NUM})">([^<]*)</text>', svg):
        x, y, fs, s = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)
        w = tw(s, fs); inner.append((x - w / 2, y - fs * .85, x + w / 2, y + fs * .22)); inner_m.append((m.group(0), x, y, fs, s, w))
    # 引き出し線つきの地名
    G = list(re.finditer(r'<g class="pl"[^>]*>.*?</g>', svg, re.S)); L = []
    for g in G:
        s = g.group(0)
        c = re.search(rf'<circle class="ldd" cx="({NUM})" cy="({NUM})"', s)
        t = re.search(rf'<text class="lb al" style="text-anchor:\w+;pointer-events:auto" x="{NUM}" y="{NUM}" font-size="({NUM})">([^<]*)</text>', s)
        nm = re.search(r'<title>([^<]*)</title>', s).group(1)
        L.append(dict(n=nm, a=(float(c.group(1)), float(c.group(2))), fs=float(t.group(1)), s=t.group(2), w=tw(t.group(2), float(t.group(1)))))
    dots = [l["a"] for l in L]

    # エリア内の地名が、引き出し線つきの地名の「指す点」を覆っているときは、その地名を少しずらす
    # （覆ったままだと、線がその地名を横切らないよう遠くへ逃げるしかなく、地名と場所が離れてしまう）
    inner_new = {}
    def covers(b, pad=4): return [p for p in dots if b[0] - pad <= p[0] <= b[2] + pad and b[1] - pad <= p[1] <= b[3] + pad]
    def in_own(x, y, own):
        if own not in rid: return True
        X, Y = int(round((x - ox) * S)), int(round(y * S))
        return 0 <= Y < Hpx and 0 <= X < Wpx and A[Y, X] == rid[own]
    for qi, (tag, x, y, fs, nm, w) in enumerate(inner_m):
        if not covers(inner[qi]): continue
        offs = sorted(((ddx, ddy) for ddx in range(-40, 41, 2) for ddy in range(-30, 31, 2)), key=lambda o: math.hypot(o[0], o[1] * 1.3))
        for ddx, ddy in offs:
            nb = (inner[qi][0] + ddx, inner[qi][1] + ddy, inner[qi][2] + ddx, inner[qi][3] + ddy)
            if covers(nb, 6): continue
            if any(box_ov(nb, q) for j, q in enumerate(inner) if j != qi): continue
            if not in_own(x + ddx, y + ddy - fs * .3, nm): continue
            inner[qi] = nb; inner_new[tag] = tag.replace(f'x="{inner_m[qi][0].split(chr(34))[3]}" y="{inner_m[qi][0].split(chr(34))[5]}"', f'x="{x + ddx:.1f}" y="{y + ddy:.1f}"')
            break

    def geom(l, side, dx, dy):
        ax, ay = l["a"]; fs = l["fs"]; ty = ay + dy
        ex = ax - dx if side == "L" else ax + dx
        tx = ex - 3 if side == "L" else ex + 3
        box = (tx - l["w"], ty - fs * .85, tx, ty + fs * .22) if side == "L" else (tx, ty - fs * .85, tx + l["w"], ty + fs * .22)
        ly = ty - fs * .32; elbow = (ex + (5 if side == "L" else -5), ly)
        return dict(side=side, ex=ex, tx=tx, ty=ty, box=box, seg=((ax, ay), elbow), tail=(elbow, (ex, ly)))

    # 候補と、他の地名に左右されない部分の点数
    span = maxx - minx
    for i, l in enumerate(L):
        fs = l["fs"]; cands = []
        for side in ("L", "R"):
            for dx in (8, 14, 22, 32, 44, 58, 75, 95, 118, 145, 175, 210, 250):
                for k in range(-26, 27):
                    dy = k * fs * .5
                    c = geom(l, side, dx, dy); b = c["box"]
                    if b[1] < 2 or b[3] > H - 2: continue
                    if any(box_ov(b, q) for q in inner): continue
                    dlen = math.hypot(c["seg"][1][0] - l["a"][0], c["seg"][1][1] - l["a"][1])
                    cost = dlen + 0.012 * dlen * dlen                                  # 指す点から遠いほど急に悪くする（遠くの海より、近くの陸地の上を選ぶ）
                    cost += sum(2e4 for q in inner if seg_box(c["seg"][0], c["seg"][1], q, 0.5))   # 線がエリア内の地名を横切る（指す点がその下にあるときは避けられない）
                    cost += 320 * land_frac(b, l["n"])                                 # 他の地域の上にかかる（自分の地域の上は軽く）
                    over = max(0, minx - 8 - b[0]) + max(0, b[2] - (maxx + 8))
                    cost += 2.2 * over                                                 # 地図の外に大きくはみ出す（地図が小さくなる）
                    cost += sum(4000 for j, p in enumerate(dots) if j != i and b[0] - 3 <= p[0] <= b[2] + 3 and b[1] - 3 <= p[1] <= b[3] + 3)
                    cost += 16 * abs(dy) / fs                                         # 真横に近いほうが読みやすく、地名と場所の対応が分かりやすい
                    c["c0"] = cost; cands.append(c)
        cands.sort(key=lambda c: c["c0"]); l["cands"] = cands[:300]

    def pair(c, d):                              # 2つの地名の置き方の相性（大きいほど悪い）
        p = 0.0
        if box_ov(c["box"], d["box"]): p += 1e5
        if seg_x(*c["seg"], *d["seg"]): p += 3e4
        if seg_box(*c["seg"], d["box"]) or seg_box(*d["seg"], c["box"]): p += 3e4
        return p

    n = len(L); cur = [0] * n
    near = [[j for j in range(n) if j != i and math.dist(L[i]["a"], L[j]["a"]) < 560] for i in range(n)]
    memo = {}
    def pc(i, k, j, q):                          # 置き方どうしの相性（覚えておいて使い回す）
        key = (i, k, j, q) if i < j else (j, q, i, k)
        v = memo.get(key)
        if v is None: v = memo[key] = pair(L[i]["cands"][k], L[j]["cands"][q])
        return v
    def cost_i(i, k): return L[i]["cands"][k]["c0"] + sum(pc(i, k, j, cur[j]) for j in near[i])
    order = sorted(range(n), key=lambda i: -sum(1 for j in range(n) if j != i and math.dist(L[i]["a"], L[j]["a"]) < 90))
    placed = set()
    for i in order:                              # 混んでいるところから順に、仮の置き場所を決める
        cur[i] = min(range(len(L[i]["cands"])), key=lambda k: L[i]["cands"][k]["c0"] + sum(pc(i, k, j, cur[j]) for j in near[i] if j in placed))
        placed.add(i)
    # 焼きなまし: ときどき悪くなる入れ替えも受け入れて、行き詰まりから抜け出す（乱数の種を固定して毎回同じ結果に）
    import random
    rnd = random.Random(7); total = sum(L[i]["cands"][cur[i]]["c0"] for i in range(n)) + sum(pc(i, cur[i], j, cur[j]) for i in range(n) for j in near[i] if j > i)
    best_total, best = total, cur[:]
    steps = 90000; T0, T1 = 400.0, 2.0
    for it in range(steps):
        T = T0 * (T1 / T0) ** (it / steps)
        i = rnd.randrange(n); nc = len(L[i]["cands"])
        k = rnd.randrange(min(nc, 60)) if rnd.random() < 0.7 else rnd.randrange(nc)
        if k == cur[i]: continue
        d = cost_i(i, k) - cost_i(i, cur[i])
        if d < 0 or rnd.random() < math.exp(-d / T):
            cur[i] = k; total += d
            if total < best_total - 1e-6: best_total, best = total, cur[:]
    cur = best
    for _ in range(10):                          # 仕上げ: 1つずつ一番よい置き場所へ
        changed = False
        for i in order:
            k = min(range(len(L[i]["cands"])), key=lambda k: cost_i(i, k))
            if cost_i(i, k) < cost_i(i, cur[i]) - 1e-6: cur[i] = k; changed = True
        if not changed: break
    badp = [(L[i]["n"], L[j]["n"]) for i in range(n) for j in range(i + 1, n) if pair(L[i]["cands"][cur[i]], L[j]["cands"][cur[j]]) > 0]
    bad = len(badp)
    if badp: print("  残った重なり・交差:", badp)

    # SVG に反映
    out = []; pos = 0; xs = [minx, maxx]
    for g, l, k in zip(G, L, cur):
        c = l["cands"][k]; s = g.group(0); ax, ay = l["a"]; ly = c["seg"][1][1]
        s = re.sub(r'points="[^"]*"', f'points="{ax:.1f},{ay:.1f} {c["seg"][1][0]:.1f},{ly:.1f} {c["ex"]:.1f},{ly:.1f}"', s, count=1)
        s = re.sub(rf'style="text-anchor:\w+;pointer-events:auto" x="{NUM}" y="{NUM}"',
                   f'style="text-anchor:{"end" if c["side"] == "L" else "start"};pointer-events:auto" x="{c["tx"]:.1f}" y="{c["ty"]:.1f}"', s, count=1)
        out.append(svg[pos:g.start()]); out.append(s); pos = g.end(); xs += [c["box"][0], c["box"][2]]
    out.append(svg[pos:]); svg2 = "".join(out)
    for t0, t1 in inner_new.items():
        assert svg2.count(t0) == 1; svg2 = svg2.replace(t0, t1)
    x0 = math.floor(min(xs + [q[0] for q in inner]) - 6); x1 = math.ceil(max(xs + [q[2] for q in inner]) + 6)
    svg2 = re.sub(r'viewBox="[^"]+"', f'viewBox="{x0} 0 {x1 - x0} {vb[3]:g}"', svg2, count=1)
    dist = [math.dist(l["a"], l["cands"][k]["seg"][1]) for l, k in zip(L, cur)]
    if os.environ.get("MAPDBG"):
        for l, k in zip(L, cur):
            c = l["cands"][k]; print("   ", l["n"], c["side"], round(math.dist(l["a"], c["seg"][1]), 1), "c0=", round(c["c0"]), "best c0=", round(l["cands"][0]["c0"]), "a=", l["a"])
    return svg2, dict(labels=n, conflicts=bad, mean_leader=round(sum(dist) / max(1, n), 1), max_leader=round(max(dist or [0]), 1))


def main(site):
    for lang in ("ja", "zh", "en"):
        p = os.path.join(site, "data", f"ui_{lang}.json"); U = json.load(open(p, encoding="utf-8"))
        for m in ("taiwan", "japan"):
            for v in ("pc", "mobile"):
                svg = U["m"][m]["map"][v]
                for _ in range(4):                  # ずらした地名がさらに別の点にかかる場合があるので、変わらなくなるまで繰り返す（何度実行しても同じ結果に）
                    new, info = relayout(svg)
                    if new == svg: break
                    svg = new
                U["m"][m]["map"][v] = svg
                print(lang, m, v, info)
        json.dump(U, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main(sys.argv[1])
