# uv 利用ルール

Python script の実行と依存の管理を uv で行うときのルール。版番号の選定と記入を uv に任せ、人と AI が版番号を手で書かずに済むようにする。

---

## 実行 [MANDATORY]

- Python script は `uv run` で実行する。システムの `python3` で直接実行しない
- 依存と Python の版は、script ごとに PEP 723 のインラインメタデータで宣言する。`uv run` は宣言を満たす Python と依存を用意してから実行する

```python
# /// script
# requires-python = ">=3.15"
# dependencies = ["foo>=1.2.0"]
# ///
```

---

## 依存の追加と削除 [MANDATORY]

- 依存は `uv add --script <script> --bounds lower <package>` で加える。uv が解決した版を下限として宣言に書き込む
- 依存は `uv remove --script <script> <package>` で外す
- 版番号を手で書かない。手で書くと、書き手が知っている古い版が下限になり、既知の脆弱性を含む版での実行を許す

---

## ロック

- `uv lock --script <script>` で、解決した版をロックファイルに固定する。ロックファイルは script と一緒に commit する
- `uv run --locked --exclude-newer "3 days"` で、ロックファイルが宣言と食い違っていないことを確かめて実行する。ロックは「公開直後の版を取り込まない」の基準を記録しているため、実行にも同じ `--exclude-newer "3 days"` を付ける。付けないと `--locked` はロックの更新が要ると判定して失敗する。`--locked` を外すと、uv はその基準を消してロックファイルを黙って書き換える

---

## 更新

- 古くなった依存は `uv tree --script <script> --outdated` で確かめる
- 更新は `uv lock --script <script> --upgrade`（全部）または `--upgrade-package <package>`（個別）で行う
- 更新したらロックファイルの差分を読み、版が上がった依存と、新しく入った依存を確かめてから commit する

---

## 公開直後の版を取り込まない

乗っ取られたパッケージの新しい版に不正なコードを仕込む攻撃では、公開から発覚・取り下げまでの間に取り込んだ利用者が被害を受ける。

- 依存の追加・ロック・更新では `--exclude-newer "3 days"`（または環境変数 `UV_EXCLUDE_NEWER="3 days"`）を付け、公開から 3 日未満の版を候補から外す
- 3 日とするのは、確認されている乗っ取り事例が公開から数時間〜1 日未満で発覚・取り下げられており、3 日あれば十分に余裕があるため。依存更新ツール Renovate が PyPI 向けに用意している公式プリセットも 3 日である
- 脆弱性の修正版を急いで取り込むときは、`--exclude-newer-package <package>=<日時>` でそのパッケージだけ基準の日時を遅らせる。その版の変更内容と公開元を確かめてから使う
- この待ち期間で防げるのは、公開後すぐに発覚する攻撃だけである。長期間気づかれない攻撃は防げない

---

## Python の版

- `requires-python` の下限は、最新の安定版に合わせる。手元に無ければ uv がダウンロードする
- 利用できる版は `uv python list` で確かめる
