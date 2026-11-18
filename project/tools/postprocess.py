"""書き出し後の仕上げ（静的サイト版だけの変更）。export_ui.py / export_pages.py のあとに必ず実行する。
使い方: python tools/postprocess.py site

  1. 日本語の診断ボタンの文言を「この条件で探す」に（説明文の「診断ボタン」も合わせる）
  2. 地図（PC・スマホ）の地名を、引き出し線が重ならず指す場所の近くに来るよう置き直す（tools/map_labels.py）
何度実行しても同じ結果になります。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from map_labels import main as relabel

JA = [("この条件で診断する", "この条件で探す"),
      ("診断ボタンを押してください", "「この条件で探す」を押してください"),
      ("診断ボタンを押すと", "「この条件で探す」を押すと"),
      ("条件を入れて診断、", "条件を入れて探す、")]

def main(site):
    p = os.path.join(site, "data", "ui_ja.json")
    s = open(p, encoding="utf-8").read(); n = 0
    for a, b in JA:
        n += s.count(a); s = s.replace(a, b)
    json.loads(s)
    open(p, "w", encoding="utf-8").write(s)
    print(f"ui_ja.json: 文言の置き換え {n} か所")
    relabel(site)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "site")
