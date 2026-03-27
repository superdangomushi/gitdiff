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
| `Ctrl+R` | 削除行の表示/非表示を切替 |
| `Ctrl+P` | エディタパネルの表示/非表示を切替 |
| `q` | 終了 |

## 技術スタック

- [Textual](https://github.com/Textualize/textual) — TUI フレームワーク
- [Rich](https://github.com/Textualize/rich) — リッチテキスト描画
