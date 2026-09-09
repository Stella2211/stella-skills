import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

// All tool state lives outside the caller's project and the installed skill.
const skill = resolve(import.meta.dir, "..");

function within(parent: string, child: string): boolean {
  const rel = relative(parent, child);
  return rel === "" || (!rel.startsWith(`..${sep}`) && rel !== ".." && !isAbsolute(rel));
}

async function canonical(path: string): Promise<string> {
  try { return await realpath(path); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    return join(await canonical(dirname(path)), path.slice(dirname(path).length + 1));
  }
}

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--help") {
    console.log("Usage: bun /path/to/docs-writer/scripts/lint-docs.ts <file.md|file.txt> [files...]\nPaths are relative to your current directory. No globs or directories.\nDOCS_WRITER_CACHE_DIR: absolute cache directory outside the project.\nExit codes: 0 clean, 1 lint findings, 2 execution failure.");
    return 0;
  }
  if (!args.length) throw new Error("対象ファイルを指定してください。使い方は --help を参照してください。");
  const caller = await realpath(process.cwd());
  const node = Bun.which("node");
  if (!node) throw new Error("Node.js が必要です。");
  const files = await Promise.all(args.map(async (arg) => {
    const path = await realpath(resolve(caller, arg));
    if (!(await stat(path)).isFile() || !/\.(md|markdown|txt)$/i.test(path)) {
      throw new Error(`Markdown またはテキストファイルを指定してください: ${arg}`);
    }
    return path;
  }));

  const override = process.env.DOCS_WRITER_CACHE_DIR;
  if (override && !isAbsolute(override)) throw new Error("DOCS_WRITER_CACHE_DIR は絶対パスで指定してください。");
  const root = await canonical(override || join(homedir(), ".cache", "stella-skills", "docs-writer"));
  // Check the Git root too when invoked from a project subdirectory.
  const git = Bun.which("git");
  const projectRoots = [caller, await realpath(resolve(skill, "../..")), ...files.map(dirname)];
  if (git) {
    for (const cwd of new Set([caller, ...files.map(dirname)])) {
      const result = Bun.spawnSync([git, "rev-parse", "--show-toplevel"], { cwd, stdout: "pipe", stderr: "ignore" });
      if (result.exitCode === 0) projectRoots.push(await realpath(result.stdout.toString().trim()));
    }
  }
  if (projectRoots.some((path) => within(path, root))) {
    throw new Error("キャッシュは対象プロジェクトとスキルの外に指定してください (DOCS_WRITER_CACHE_DIR)。");
  }
  const manifest = await readFile(join(skill, "assets/runtime/package.json"));
  const lock = await readFile(join(skill, "assets/runtime/bun.lock"));
  const config = await readFile(join(skill, "assets/textlintrc.json"));
  const key = createHash("sha256").update(manifest).update(lock).update(config)
    .update(`${process.platform}-${process.arch}-${Bun.version}`).digest("hex").slice(0, 24);
  const runtime = join(root, key);
  const cli = join(runtime, "node_modules/textlint/bin/textlint.js");
  if (!(await Bun.file(join(runtime, ".ready")).exists()) || !(await Bun.file(cli).exists())) {
    await mkdir(root, { recursive: true });
    const staging = await mkdtemp(join(root, ".install-"));
    try {
      await Promise.all([
        writeFile(join(staging, "package.json"), manifest),
        writeFile(join(staging, "bun.lock"), lock),
        writeFile(join(staging, "textlintrc.json"), config),
        writeFile(join(staging, ".textlintignore"), ""),
      ]);
      console.error("docs-writer: 専用キャッシュに依存をセットアップします。");
      const install = Bun.spawn([process.execPath, "install", "--frozen-lockfile", "--ignore-scripts"], {
        cwd: staging, stdout: "inherit", stderr: "inherit",
      });
      if (await install.exited !== 0) throw new Error("依存のセットアップに失敗しました。ネットワークとキャッシュへの書き込み権限を確認してください。");
      await writeFile(join(staging, ".ready"), "ready\n");
      // Publishing only a complete directory lets simultaneous first runs coexist.
      try { await rename(staging, runtime); }
      catch (error) {
        if (!(await Bun.file(join(runtime, ".ready")).exists()) || !(await Bun.file(cli).exists())) {
          throw new Error(`キャッシュを公開できませんでした。破損したキャッシュ ${runtime} を削除して再実行してください。原因: ${error}`);
        }
      }
    } finally { await rm(staging, { recursive: true, force: true }); }
  }
  let status = 0;
  for (const path of new Set(files)) {
    // stdin avoids glob interpretation of literal filenames and project config discovery.
    const child = Bun.spawn([node, cli, "--config", join(runtime, "textlintrc.json"),
      "--ignore-path", join(runtime, ".textlintignore"), "--stdin", "--stdin-filename", path], {
      cwd: runtime, stdin: Bun.file(path), stdout: "inherit", stderr: "inherit",
    });
    const code = await child.exited;
    status = Math.max(status, code === 0 ? 0 : code === 1 ? 1 : 2);
  }
  return status;
}

try { process.exitCode = await main(); }
catch (error) {
  console.error(`docs-writer: ${error instanceof Error ? error.message : error}`);
  process.exitCode = 2;
}
