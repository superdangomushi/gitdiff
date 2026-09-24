# gitdiff

Git ブランチ間の差分をターミナル上でインタラクティブに閲覧・編集できる TUI ツールです。

## 概要

- **3ペインレイアウト** — ファイル一覧 / diff ビュー / エディタを一画面で表示
- **インライン編集** — diff を見ながらその場でファイルを編集・保存
- **シンタックスハイライト** — 20以上の言語に対応した色付き diff 表示
- **ステータス表示** — 追加(A)・変更(M)・削除(D)・リネーム(R) などを色分け表示
- **ブランチ切替** — 比較対象のブランチをその場で変更可能
- **動作環境** - pythonが必要です。windows環境ならwingetなりでインストールしたら早いかも
```bash
winget install python
```

## インストール

### macOS / Linux

```bash
git clone https://github.com/superdangomushi/gitdiff.git
cd gitdiff
./install.sh
```

### Windows (Git Bash)

```bash
git clone https://github.com/superdangomushi/gitdiff.git
cd gitdiff
./install-win.sh
```

Git Bash と CMD / PowerShell の両方で使えるラッパーが生成されます。

> `~/.local/bin` が PATH に含まれていない場合は、スクリプトの案内に従って追加してください。

## アンインストール

```bash
# macOS / Linux
./remove.sh

# Windows (Git Bash)
./remove-win.sh
```

## 使い方

```bash
gitdiff <branch-a> [<branch-b>]
```

`<branch-b>` を省略すると `HEAD` が使われます。

### 例

```bash
# main と現在のブランチを比較
gitdiff main

# 2つのブランチを比較
gitdiff main feat/new-feature
```

## キーバインド

| キー | 操作 |
|------|------|
| `j` / `k` / `↑` / `↓` | ファイル一覧のナビゲーション |
| `e` | 選択中のファイルを編集モードで開く |
| `b` | 比較ブランチを変更 |
| `Ctrl+D` / `Ctrl+U` | diff ビューのページ送り |
| `Ctrl+G` | ファイル一覧にフォーカスを戻す |
| `Ctrl+S` | ファイルを保存 |
| `Ctrl+X` | ファイルをディスク上の状態に戻す |
| `Ctrl+R` | 削除行の表示/非表示を切替（プレビューのみ） |
| `Backspace`（赤い削除行上） | 編集モードでその削除行を復元 |
| `Ctrl+P` | エディタパネルの表示/非表示を切替 |
| `Ctrl+F` | ファイル一覧とエディタのみの表示に切替（diff ビューを隠す） |
| クリック（黄色い行） | その行の PR レビューコメントを diff ビューの位置に表示 |
| `Esc` | コメント表示を閉じる / 編集モードを抜ける |
| `q` | 終了 |

### PR レビューコメント

[GitHub CLI (`gh`)](https://cli.github.com/) がインストール・ログイン済みなら、比較先ブランチ（省略時は現在のブランチ）から出ている PR のレビューコメントを起動時に取得します。

- コメントのある行はエディタ画面で黄色く表示され、クリックするとコメントツリーが diff ビューに表示されます
- ファイル一覧にはファイルごとのコメントスレッド数が表示されます
- `gh` が無い・PR が無い場合は何も表示されません

## 技術スタック

- [Textual](https://github.com/Textualize/textual) — TUI フレームワーク
- [Rich](https://github.com/Textualize/rich) — リッチテキスト描画

## コード構成

`gitdiff.py` は起動専用です。実装は `gitdiff_tui/` にあり、アプリ全体の状態と操作の連携を `GitDiffApp` が担当します。差分の解析は UI に依存せず、画面部品は `widgets/`、見た目は `styles/` に分かれています。

```text
gitdiff.py                     # 既存の起動口（インストーラもここを呼ぶ）
gitdiff_tui/
├── cli.py                     # 引数・補完・起動前のチェック
├── app.py                     # GitDiffApp：状態・キー割り当て・画面構成
├── git.py                     # Git コマンド、差分・ブランチ情報の取得
├── github.py                  # gh による PR レビューコメント取得
├── models.py                  # ReviewComment / ReviewThread のデータ定義
├── diff.py                    # 差分解析、編集バッファ生成、行番号の追従
├── review_mapping.py          # コメントと差分・編集行の対応付け
├── rendering.py               # Rich による表示内容、ステータス色・ラベル
├── languages.py               # 拡張子とハイライト言語の対応
├── controllers/               # GitDiffApp の処理を責務ごとに分けた Mixin
│   ├── navigation.py          # カーソル移動、スクロール、フォーカス
│   ├── layout.py              # パネルの表示切替、スプリッター
│   ├── file_list.py           # ファイルツリー構築、ブランチ変更
│   ├── diff_view.py           # 差分・エディタプレビューの描画
│   ├── editing.py             # 編集モード、保存、元に戻す
│   └── review.py              # PR レビューコメントの取得・表示
├── widgets/
│   ├── panels.py              # FilePanel / DiffPanel / EditorPanel の構成
│   ├── file_tree.py           # FileTree：ディレクトリ表示、ファイルラベル
│   ├── editor.py              # DiffTextArea：編集、削除行の保護・復元
│   ├── preview.py             # EditorView：差分プレビューのクリック処理
│   └── splitter.py            # PanelSplitter：ドラッグでパネル幅を調整
├── screens/
│   └── branch.py              # ChangeBranchScreen：ブランチ変更ダイアログ
└── styles/
    ├── app.tcss               # メイン画面のレイアウト・配色
    └── branch.tcss            # ダイアログのレイアウト・配色
tests/                         # 差分処理と画面操作の回帰テスト
```

ファイル選択時は、`controllers/diff_view.py` が `git.py` から差分を取得し、`diff.py` と `review_mapping.py` で表示用データを作り、画面部品を更新します。編集時の削除行の扱いは `widgets/editor.py`、保存先への書き込みは `controllers/editing.py` が担当します。

パネルの配置・構成を変える場合は `widgets/panels.py`、配色や幅を変える場合は `styles/`、キー操作を追加する場合は `app.py` の `BINDINGS` と `action_*` を編集します。

## 開発・テスト

Textual と Rich をインストールした Python 環境で、リポジトリのルートから実行します。テストには標準ライブラリの `unittest` と Textual のヘッドレス実行を使用し、GitHub への通信は行いません。

```bash
python -m unittest discover -s tests -v
python gitdiff.py --help
```

macOS / Linux のインストーラで作成した環境を使う場合は、`python` の代わりに `~/.local/share/gitdiff-venv/bin/python` を指定できます。
