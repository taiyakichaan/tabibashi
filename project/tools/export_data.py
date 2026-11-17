"""元アプリ(Python版)から、ブラウザ版で使うデータ・モデルを JSON に書き出す。
使い方: python tools/export_data.py <元アプリのフォルダ> <出力先 site フォルダ>

書き出すもの（site/data/ 以下）
  model_<market>.json : ロジスティック回帰の係数・切片・標準化の平均/標準偏差・One-Hot のカテゴリ
  spots_<market>.json : app.py が読み込み時に整えた後のスポット表のうち、推薦の計算に使う列（地域・スポット名・好みの点数・観光価値）
  meta.json           : 推薦の計算に使う定数（POP定番度・base平均的旅行者・BLOCKS・為替・FIRST_W など）
  その他 data/*.json  : 元アプリの JSON をそのままコピー
画像は images/ をそのまま site/images/ にコピーする。
"""
import json, math, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from load_app import load, ascii_name


def clean(v):
    """numpy / pandas の値を JSON に書ける素の値へ。NaN は None。"""
    import numpy as np
    if v is None: return None
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v); return None if math.isnan(f) else f
    if isinstance(v, (np.bool_,)): return bool(v)
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    if isinstance(v, dict): return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, np.ndarray): return [clean(x) for x in v.tolist()]
    return v


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def model_json(d):
    pipe = d["model"]; pre = pipe.named_steps["pre"]; clf = pipe.named_steps["clf"]
    cat_name, ohe, cat_cols = pre.transformers_[0]
    _, scaler, num_cols = pre.transformers_[1]
    assert cat_name == "cat" and list(cat_cols) == ["party_type"]
    return dict(
        algo=type(clf).__name__,
        feats=list(d["feats"]),                       # 入力の列順（app.py の d["feats"]）
        onehot=dict(col="party_type", categories=[str(c) for c in ohe.categories_[0]]),
        num_cols=list(num_cols), mean=clean(scaler.mean_), scale=clean(scaler.scale_),
        classes=[str(c) for c in clf.classes_], coef=clean(clf.coef_), intercept=clean(clf.intercept_),
    )


def main(app_dir, site_dir):
    app_dir, site_dir = os.path.abspath(app_dir), os.path.abspath(site_dir)
    a = load(app_dir)
    import fx
    out = os.path.join(site_dir, "data"); os.makedirs(out, exist_ok=True)
    meta = dict(
        SPOT_COLS=a.SPOT_COLS, CORE=a.CORE, ALL=a.ALL, KEYS=a.KEYS, FIRST_W=a.FIRST_W,
        PARTY=[k for k, _ in a.PARTY],
        FX=dict(PER_USD=fx.PER_USD, BASE=fx.BASE, DEFAULT_BASE=fx.DEFAULT_BASE, LOCAL=fx.LOCAL, STEP=fx.STEP),
        BLOCKS=a.BLOCKS, POP={m: clean(a.POP[m]) for m in a.D}, BASE_ROW={m: clean(a.D[m]["base"]) for m in a.D},
        EVAL=a.EVAL,
    )
    dump(meta, os.path.join(out, "meta.json"))
    for m, d in a.D.items():
        dump(model_json(d), os.path.join(out, f"model_{m}.json"))
        sp = d["spots"]
        rows = []
        keep = ["region", "spot"] + list(a.SPOT_COLS) + ["tourism_value_score"]     # 推薦の計算に使う列だけ（スポットの表示は書き出したページの HTML を使う）
        for rec in sp[keep].to_dict(orient="records"):
            r = {}
            for k, v in rec.items():
                v = clean(v)
                if v is None or v == "": continue
                r[k] = v
            rows.append(r)
        dump(rows, os.path.join(out, f"spots_{m}.json"))
        print(f"{m}: spots={len(rows)} classes={len(d['model'].classes_)}")
    for fn in sorted(os.listdir(os.path.join(app_dir, "data"))):           # 元の JSON はそのままコピー
        if fn.endswith(".json"): shutil.copy2(os.path.join(app_dir, "data", fn), os.path.join(out, fn))
    src_img, dst_img = os.path.join(app_dir, "images"), os.path.join(site_dir, "images")
    if os.path.isdir(src_img):                     # 画像は英字のファイル名でコピー（日本語名は公開先で文字化けすることがあるため）
        if os.path.isdir(dst_img): shutil.rmtree(dst_img)
        seen = {}
        for root, _, files in os.walk(src_img):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), app_dir)
                new = ascii_name(a, rel)
                assert new not in seen, f"英字の名前が重なる: {rel} / {seen[new]}"
                seen[new] = rel
                os.makedirs(os.path.dirname(os.path.join(site_dir, new)), exist_ok=True)
                shutil.copy2(os.path.join(app_dir, rel), os.path.join(site_dir, new))
        print(f"images: {len(seen)} files（英字の名前に変えたもの {sum(1 for k, v in seen.items() if k != v.replace(os.sep, '/'))}）")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
