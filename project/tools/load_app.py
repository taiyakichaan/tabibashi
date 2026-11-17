"""元の app.py を読み込むための共通処理。起動時の先読み（天気取得・全ページ生成）は止めて、計算部分だけ使う。
使い方: from load_app import load; app = load("<元アプリのフォルダ>")"""
import os, sys, threading

def load(app_dir):
    app_dir = os.path.abspath(app_dir)
    os.chdir(app_dir); sys.path.insert(0, app_dir)
    _start = threading.Thread.start
    def start(self):
        if getattr(self, "_target", None) is not None and getattr(self._target, "__name__", "") == "_prewarm": return
        return _start(self)
    threading.Thread.start = start
    try:
        import app
    finally:
        threading.Thread.start = _start
    return app


# ---- 画像のファイル名を英字にそろえる ----
# 日本語のファイル名（images/regions/北海道.jpg など）は、zip の展開・Git・Windows などで文字化けしたり別の文字に
# 正規化されたりして、公開先で「画像が見つからない」原因になる。エリアの英語名（app.py の TW_EN / JP_EN）から英字の名前を作る。
def ascii_name(app, rel):
    import re
    rel = rel.replace(os.sep, "/")
    d, f = os.path.split(rel)
    if all(ord(c) < 128 for c in f): return rel
    stem, ext = os.path.splitext(f)
    en = app.TW_EN.get(stem) or app.JP_EN.get(stem)
    if not en: raise ValueError(f"英字の名前を決められない画像: {rel}")
    return f"{d}/{re.sub(r'[^a-z0-9]+', '-', en.lower()).strip('-')}{ext}"


def asset_url(app):
    """元の asset()（/gradio_api/file=<絶対パス>）の代わり。サイトのルートからの絶対パス /images/... を返す"""
    from urllib.parse import quote
    return lambda p: "/" + quote(ascii_name(app, p), safe="/")
