# 使用したスキルだけをCompaction後に復元する

`docs-writer`と`long-task-execution`は、それぞれ独立した使用登録ヘルパーとHookを同梱します。スキルを現在の作業に適用したスレッドだけに本文を再投入します。未登録なら何も出力しません。

## 導入

両プラグインを0.1.1以降へ更新し、Codexの`/hooks`でプラグインのHook定義を確認・信頼してください。プラグインのインストールだけでHookが信頼済みになるわけではありません。ユーザー設定に以前の全スキル再投入Hookがある場合は、その定義だけを外して二重投入を避けます。

各環境で、`uv`とuvから利用できるPython 3.10以降を用意します。Hookは`--offline --no-project`で実行し、実行中に依存やPythonをダウンロードしません。必要なら起動前の環境設定で`UV_PYTHON`に既存のPythonを指定します。

HookのコマンドはPython内で`PLUGIN_ROOT`を読むため、ユーザー名、プラグインの版別パス、POSIXとWindowsの環境変数展開構文を固定しません。実際に使用するCodexでの発火・信頼設定・sandboxの確認は、自動テストと区別してください。

## 使用登録

適用するエージェント自身が、現在のスキル一覧にあるSKILL.mdのパスから`../../hooks/skill-usage.py`を解決し、絶対パスで一度だけ実行します。

```sh
uv run --offline --no-project python "/absolute/plugin/path/hooks/skill-usage.py" activate
```

これはSkillの使用を明示する操作であり、SKILL.mdの閲覧・レビュー・編集だけでは登録しません。繰り返し実行しても、同じ空のマーカーを維持します。登録済みかを毎ターン確認する必要はありません。

スレッドIDはネイティブシェルの`CODEX_THREAD_ID`から取得します。CLI引数による他スレッドの指定や、親IDへのフォールバックはありません。親の登録を子へ委任しないでください。子が自分で適用したスキルは子のIDに登録し、親の登録へ合流させません。

`my-codex-settings`のAGENTS.mdにある限定的な使用登録例外と併用します。登録できない場合は、その事実を一度報告し、現在読めるスキル本文に従って作業を続けます。登録のためだけにsandboxを無効化したり、別スレッドのIDを使ったりしません。

用途を切り替える場合は、同じヘルパーで解除できます。

```sh
uv run --offline --no-project python "/absolute/plugin/path/hooks/skill-usage.py" deactivate
uv run --offline --no-project python "/absolute/plugin/path/hooks/skill-usage.py" status
```

`status`は状態を表示するだけで、登録を作りません。登録・解除の失敗は終了コード1です。

## 状態の保存先

既定の保存先は次です。

```text
${CODEX_HOME:-~/.codex}/stella-skills/skill-usage/
  <実行スレッドID>/
    docs-writer.active
    long-task-execution.active
```

マーカーは空ファイルで、Skill本文やインストール場所を保存しません。コードやプロジェクトの進捗には混ぜません。プラグイン更新後は、同じ登録を使い、現在インストールされている本文を読みます。

`STELLA_SKILL_USAGE_DIR`に絶対パスを指定すると保存先を変更できます。登録するシェルとHookで、同じ`CODEX_HOME`または同じ上書き先が見えるよう、Codexの起動環境で設定してください。通常のシェルにない可能性がある`PLUGIN_DATA`は使用しません。

書き込み先は、登録するシェルの既存権限でアクセスできる必要があります。読み取り専用環境などでは、許可済みの保存先を指定するか、登録を見送ります。未登録のHookは保存ディレクトリを作りません。

登録はローカル状態です。同じスレッドを別PCへ移す場合は、その環境で再登録するか、必要なマーカーだけを引き継ぎます。通常終了や同じ会話の再開では削除しません。

## Compactionとclear

Hookは`SessionStart`の`compact`と`clear`だけに一致します。

`compact`ではイベントの`session_id`に対する自分のマーカーを確認します。登録済みなら自分のSKILL.mdを読み、本文と参照解決用の実パスを`additionalContext`へ返します。未登録なら本文を読まず、標準出力も出しません。

`clear`では、そのイベントのIDに対応する自分のマーカーだけを削除します。新しい会話IDは未登録から始まります。過去の別IDのマーカーを走査・削除する処理はありません。

対象は親セッションのCompactionです。子の使用登録によって親へ本文が入ることはありません。子のCompaction後に同じイベントが必ず発生するとは仮定しません。Hookへ`agent_id`が付いたイベントは処理しません。

最初の登録操作はエージェントの指示遵守に依存します。Hookは未登録の使用を推測せず、セッションJSONLを解析しません。復元された本文を理由に再登録や無関係な作業を開始しません。

## 出力量と失敗時の扱い

入力イベントは64 KiB、Skill本文は16 KiB、追加文脈全体は20 KiBまでに制限します。上限超過や読めないファイルは、本文の一部だけを投入せず、標準エラーへ理由を書いて終了します。`additionalContextLimit: 0`は、このスクリプト側の上限と組み合わせています。

Hook側の処理エラーは終了コード0で返し、ユーザーの本来のタスクを停止させません。全スキル投入へのフォールバックはありません。uvやPython自体の起動失敗、Codex側のタイムアウトは、ヘルパー内のエラー処理とは別です。

## 検証

```sh
uv run --offline --no-project python -m unittest discover -s tests -p test_skill_usage.py -v
```

自動テストは、登録・未登録、親子とプラグインの分離、解除、clear、通常再開、異常入力、上限、保存先、プラグイン移動、実際のHookコマンドを扱います。GitHub ActionsでLinux・macOS・Windowsを対象にします。テストの通過と、Codex実機でのHook発火は別の確認です。

実機では未登録の会話をcompactし、本文が入らないことを確認します。次に片方だけを採用・登録してcompactし、その本文だけが入ることを確認してください。子だけの採用で親に本文が入らないことも確認対象です。

## 参照

- [OpenAIのHook仕様](https://learn.chatgpt.com/docs/hooks)：イベント、プラグイン環境変数、出力、信頼設定。
- [CodexのCODEX_THREAD_ID実装](https://github.com/openai/codex/pull/10096)：ネイティブシェルで使うスレッド識別子。
