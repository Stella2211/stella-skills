# 使用したスキルだけをCompaction後に復元する

`docs-writer`と`long-task-execution`の0.1.1以降には、スレッドごとの使用登録と、登録したスキルだけを復元するHookを同梱しています。スキル本文の既存の作業方針は維持しています。

## 動作

スキルを作業に適用したエージェントが、一度だけ自分の`CODEX_THREAD_ID`で使用登録します。単にSKILL.mdを閲覧・レビュー・編集するだけでは登録しません。

親セッションの`SessionStart`の`compact`で、各プラグインがその`session_id`のマーカーを調べます。登録があるプラグインだけ、自分のインストール済みSKILL.mdを追加文脈として返します。未登録なら本文を開かず、標準出力を空にして終了します。全スキルの代替投入、セッションJSONLの解析、追加のLLM呼び出しは行いません。

子が使ったスキルは子のスレッドに登録します。子だけがdocs-writerを使っても、親にはdocs-writerを復元しません。現在の自動復元は親のCompactionを対象とし、子のCompactionでの発火を保証する実装ではありません。新しいスレッドやfork先では必要なスキルを改めて採用・登録します。

## 導入

両プラグインを0.1.1以降へ更新し、現在のスキル一覧でプラグイン版の読み先を確認します。`/hooks`で同梱定義を確認し、各環境で信頼を登録します。インストールだけではHookの信頼登録になりません。

以前の「毎回両スキルを投入する」ユーザーHookがある場合、その再投入定義だけを外して二重投入を避けます。他のHookは保持します。ローカル版とプラグイン版の同じスキルを二重に管理しません。

`uv`とPython 3.10以降が、Codexから利用できる必要があります。Hookは`--offline --no-project`で起動し、依存関係やPythonをダウンロードしません。対応するPythonを事前に用意してください。

プラグインの実パスはHook環境の`PLUGIN_ROOT`から取得します。POSIX・Windows両コマンドでPython内でパスを解決するため、ユーザー名やインストール版の固定パス、シェルごとの環境変数展開は不要です。

## 登録・確認・解除

`<absolute-skill-path>`は、現在のスキル一覧が示すSKILL.mdのあるディレクトリに置き換えます。`PLUGIN_ROOT`は通常のエージェントシェルで利用できると仮定しません。

```sh
uv run --offline --no-project python "<absolute-skill-path>/../../hooks/skill-usage.py" activate
uv run --offline --no-project python "<absolute-skill-path>/../../hooks/skill-usage.py" status
uv run --offline --no-project python "<absolute-skill-path>/../../hooks/skill-usage.py" deactivate
```

登録・解除は冪等です。登録済みなら状態を書き直さず、定期的な更新や毎ターンのstatus確認も不要です。用途が変わり不要になったときは`deactivate`を使えます。単に返答を終えた、アプリを閉じた、同じ会話を再開したという理由では解除しません。

これらは登録するエージェント自身が実行します。親の登録を子へ委任したり、`CODEX_THREAD_ID`を別スレッドの値で上書きしたりしません。`Stella2211/my-codex-settings`の対応するAGENTS更新では、この小さな操作を直接実行の例外にしています。

`CODEX_THREAD_ID`が取得できなければ、別IDを推測せず登録を失敗として報告します。登録がないまま自動復元されるとは説明しません。登録自体を忘れた場合も自動復元されないため、SKILL.mdに採用時の操作を明記しています。

## 状態の保存先

既定では次の空マーカーファイルだけを作ります。

```text
${CODEX_HOME:-~/.codex}/stella-skills/skill-usage/<thread-id>/<plugin-name>.active
```

`STELLA_SKILL_USAGE_DIR`に絶対パスを設定すると、`<thread-id>/<plugin-name>.active`を置く基点を変更できます。この環境変数と`CODEX_HOME`は、登録用のネイティブシェルとHookに同じ値を継承させます。Hookだけに渡される`PLUGIN_DATA`は保存先に使いません。

保存先に既存のsandbox権限で書き込めない場合は、許可された狭いローカル保存先を設定するか、その場所への必要な許可を得ます。スキル登録のためにsandbox全体を無効化しません。設定の変更後、古い保存先のマーカーは自動移動しないため、必要なら現在のスレッドで再登録します。

状態はプロジェクトやインストール済みプラグインに書きません。プラグイン名とスレッドIDで識別するため、同じマシンでプラグインの版やインストール場所が変わっても登録を利用できます。別PCで同じ会話を継続する場合は、登録状態の引き継ぎか再登録が必要です。

## リセットと失敗

`SessionStart`の`clear`では、そのイベントの`session_id`に対する自分のプラグインのマーカーだけを消します。新しいIDが作られた場合、そのIDは未登録で始まります。全スレッドの履歴を削除したり、`SessionEnd`で登録を消したりしません。

Hook入力は64 KiB、SKILL.mdは16 KiB、復元する本文とヘッダーの合計は20 KiBを上限にしています。上限超過、読めないファイル、不正な入力では標準エラーへ診断を出し、部分的な本文や全スキルを投入しません。Hookはエラーでも終了コード0で作業を継続させます。登録・解除・確認コマンドのエラーは終了コード1です。

Hookの`additionalContextLimit: 0`は、スクリプト側の上限があるため指定しています。スキル本文を制限なく増やすための設定ではありません。登録マーカーは使用記録であり、セキュリティ上の認証・承認ではありません。

## 検証

リポジトリのルートで、標準ライブラリのテストを実行します。

```sh
uv run --no-project python -m unittest discover -s tests -p "test_skill_usage.py" -v
```

テストは隔離したプラグイン配置で登録、再登録、解除、スレッド分離、プラグイン分離、compact/clear、通常resume、無効入力、本文上限を確認します。uvが利用可能なら、配布するHookコマンド自体も空白・日本語を含むパスで起動します。GitHub ActionsではLinux・macOS・Windowsで実行します。

これはヘルパーとコマンドの試験です。Codex本体のHook読込、信頼登録、実際の`/compact`後の本文投入は別の実機確認です。導入時は、未採用スレッドで無出力、採用したスレッドで登録済み本文のみ、子だけが採用した場合に親へ投入しないことを確認してください。

公式仕様: [Codex Hooks](https://learn.chatgpt.com/docs/hooks)。`SessionStart`、plugin-bundled hooks、共通入力、additionalContextの仕様を参照しています。
