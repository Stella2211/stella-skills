import { afterAll, expect, test } from "bun:test";
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root = mkdtempSync(join(tmpdir(), "docs-writer-test-"));
const project = mkdtempSync(join(root, "project-"));
const cache = join(root, "cache");
const script = join(import.meta.dir, "lint-docs.ts");
const env = { ...process.env, DOCS_WRITER_CACHE_DIR: cache };
const run = (args: string[], overrides = {}) => Bun.spawnSync([process.execPath, script, ...args], {
  cwd: project, env: { ...env, ...overrides }, stdout: "pipe", stderr: "pipe",
});
const fixture = (name: string, content: string) => writeFileSync(join(project, name), content);
afterAll(() => rmSync(root, { recursive: true, force: true }));

test("isolated initial install, literal paths, project settings ignored, cache reused", () => {
  fixture("文書 [1] space.md", "# 設定\n\n設定をファイルに保存します。\n");
  fixture(".textlintrc.json", '{"rules":{"nonexistent-rule":true}}');
  fixture(".textlintignore", "*\n");
  const before = readdirSync(project).sort();
  const first = run(["文書 [1] space.md"]);
  expect(first.exitCode).toBe(0);
  expect(first.stderr.toString()).toContain("セットアップ");
  const second = run(["文書 [1] space.md"]);
  expect(second.exitCode).toBe(0);
  expect(second.stderr.toString()).not.toContain("セットアップ");
  expect(readdirSync(project).sort()).toEqual(before);
  expect(readFileSync(join(project, ".textlintignore"), "utf8")).toBe("*\n");
}, 120000);

test("reports both prohibited families with file and line; ignores project ignore file", () => {
  fixture("bad.md", "この設定は効く。\nこの実装は強い。\n");
  const result = run(["bad.md"]);
  expect(result.exitCode).toBe(1);
  const output = result.stdout.toString();
  expect(output).toContain("bad.md");
  expect(output).toContain("1:");
  expect(output).toContain("2:");
  expect(output).toContain("「効く」系");
  expect(output).toContain("「強い」系");
});

test("reports translation-like terms with actionable replacements", () => {
  fixture("terms.md", "このファイルを正本とします。\n上流の変更を取り込みます。\n");
  const result = run(["terms.md"]);
  expect(result.exitCode).toBe(1);
  const output = result.stdout.toString();
  expect(output).toContain("「正本」");
  expect(output).toContain("SSoT");
  expect(output).toContain("「上流」");
  expect(output).toContain("具体的なリポジトリ名");
  expect(output).toContain("アップストリーム");
});

test("permits the preferred replacements", () => {
  fixture("preferred.md", "このファイルをSSoTとします。\n変更をアップストリームから取り込みます。\nstella-skillsリポジトリを参照します。\n");
  expect(run(["preferred.md"]).exitCode).toBe(0);
});

test("permits quotes and code while checking prose in the same file", () => {
  fixture("quote.md", "> この設定は効く。\n> この実装は強い。\n> 正本と上流。\n\n`強い正本上流`\n\n```txt\n効く\n正本\n上流\n```\n");
  expect(run(["quote.md"]).exitCode).toBe(0);
  fixture("quote.md", "> この実装は強い。\n\nこの設定は効く。\n");
  expect(run(["quote.md"]).exitCode).toBe(1);
});

test("AI writing preset is active", () => {
  fixture("ai.md", "- **注意**: 設定を確認してください。\n");
  const result = run(["ai.md"]);
  expect(result.exitCode).toBe(1);
  expect(result.stdout.toString()).toContain("no-ai-list-formatting");
});

test("multiple files retain lint status and missing input is fatal", () => {
  fixture("ok.txt", "設定を保存します。\n");
  expect(run(["bad.md", "ok.txt"]).exitCode).toBe(1);
  expect(run(["ok.txt", "missing.md"]).exitCode).toBe(2);
  expect(run([]).exitCode).toBe(2);
});

test("rejects in-project and relative cache locations", () => {
  expect(run(["ok.txt"], { DOCS_WRITER_CACHE_DIR: join(project, "cache") }).exitCode).toBe(2);
  expect(run(["ok.txt"], { DOCS_WRITER_CACHE_DIR: "cache" }).exitCode).toBe(2);
  expect(readdirSync(project)).not.toContain("cache");
});

test("simultaneous first runs publish a reusable cache", async () => {
  const concurrentCache = join(root, "concurrent-cache");
  const children = Array.from({ length: 2 }, () => Bun.spawn([process.execPath, script, "ok.txt"], {
    cwd: project, env: { ...env, DOCS_WRITER_CACHE_DIR: concurrentCache },
    stdout: "ignore", stderr: "ignore",
  }));
  expect(await Promise.all(children.map(child => child.exited))).toEqual([0, 0]);
  const repeat = run(["ok.txt"], { DOCS_WRITER_CACHE_DIR: concurrentCache });
  expect(repeat.exitCode).toBe(0);
  expect(repeat.stderr.toString()).not.toContain("セットアップ");
}, 120000);
