# プラグインとスキルを追加する

この文書は、`stella-skills` を管理する人向けのガイドです。利用者向けのインストール方法や各スキルの使い方は、リポジトリの [README](../README.md) を参照してください。

## リポジトリ構成

マーケットプレイスのエントリと各プラグインを分け、プラグインごとに複数のスキルや参照資料を追加できる構成にしています。

```text
stella-skills/
├── .agents/
│   └── plugins/
│       └── marketplace.json
├── plugins/
│   ├── codex-sidekick/
│   │   ├── .codex-plugin/
│   │   │   └── plugin.json
│   │   └── skills/
│   │       └── codex-sidekick/
│   │           ├── SKILL.md
│   │           └── references/
│   │               ├── linux.md
│   │               ├── long-running.md
│   │               ├── macos.md
│   │               └── windows.md
│   └── docs-writer/
│       ├── .codex-plugin/
│       │   └── plugin.json
│       └── skills/
│           └── docs-writer/
│               ├── SKILL.md
│               ├── references/
│               │   └── textlint.md
│               ├── assets/
│               │   ├── textlintrc.json
│               │   └── runtime/
│               │       ├── package.json
│               │       └── bun.lock
│               └── scripts/
│                   ├── lint-docs.ts
│                   └── lint-docs.test.ts
├── docs/
│   └── adding-skills.md
└── README.md
```

## プラグインやスキルを追加する

新しいプラグインは `plugins/<plugin-name>/` に追加し、その中に `.codex-plugin/plugin.json` と `skills/<skill-name>/SKILL.md` を置きます。同じプラグインに複数のスキルを置く場合は、`skills/` の下にスキルごとのディレクトリを増やします。マーケットプレイスの `plugins` エントリからは、常にこのリポジトリのルートを基準に各プラグインを参照します。

新しい機能が既存プラグインのスキルとして収まる場合は、対象プラグインの `skills/<skill-name>/` に追加し、必要な参照資料も同じスキルのディレクトリから相対参照します。独立した設定、権限、配布単位、または複数スキルをまとめる境界が必要な場合は、新しい `plugins/<plugin-name>/` を追加します。

このリポジトリの `docs-writer` は、コードの現状に合わせた日本語ドキュメントの作成・更新と textlint による確認を扱います。スキルから参照する資料は、そのスキルの `references/` に置きます。実行用スクリプトや textlint の設定・依存関係を追加する場合も、対象プロジェクトへ書き込まない構成を保ちます。

プラグインを追加・変更したら、次を確認します。

- `.codex-plugin/plugin.json` のバージョンを変更内容に合わせて更新する。
- 新しいプラグインを追加した場合は `.agents/plugins/marketplace.json` の `plugins` 配列へエントリを追加する。既存プラグイン内へのスキル追加だけなら、新しいマーケットプレイスエントリは不要。
- マーケットプレイスの各パスがリポジトリルートからの相対パスになっていることを確認する。
- この文書の構成例と README のスキル名、参照パスを実際のファイル構成と一致させる。

## ローカルで確認する

以下は Codex CLI 0.153.4 のヘルプで確認した構文です。利用中の CLI で、先に `codex plugin --help`、`codex plugin marketplace add --help`、`codex plugin add --help` も確認してください。

リポジトリの親ディレクトリから実行する場合は、マーケットプレイスのルートを相対パスで登録します。

```sh
codex plugin marketplace add ./stella-skills
codex plugin marketplace list
codex plugin list
codex plugin add codex-sidekick@stella-skills
```

リポジトリ内から実行する場合も、登録するパスは現在のディレクトリを表す `.` です。

```sh
cd stella-skills
codex plugin marketplace add .
codex plugin marketplace list
codex plugin list
codex plugin add codex-sidekick@stella-skills
```

`marketplace add` は設定済みのマーケットプレイス一覧にローカルのマーケットプレイスを追加します。`plugin add` は、その一覧からプラグインを追加します。実際に導入する前に、利用中の CLI のヘルプと挙動を確認してください。
