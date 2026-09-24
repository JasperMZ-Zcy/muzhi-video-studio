import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const argumentsMap = new Map(
  process.argv.slice(2).map((argument) => {
    const [key, value] = argument.split("=", 2);
    return [key, value ?? true];
  }),
);

const runtimeArgument = argumentsMap.get("--runtime") || process.env.REMOTION_RUNTIME;
const outputArgument = argumentsMap.get("--output");

const hasRemotionCli = (candidate) =>
  typeof candidate === "string" &&
  existsSync(join(resolve(candidate), "node_modules", "@remotion", "cli"));

const findRuntime = () => {
  if (runtimeArgument && hasRemotionCli(runtimeArgument)) return resolve(runtimeArgument);
  let cursor = process.cwd();
  const checked = new Set();
  while (true) {
    for (const candidate of [cursor, join(cursor, "remotion-composer")]) {
      const normalized = resolve(candidate);
      if (!checked.has(normalized) && hasRemotionCli(normalized)) return normalized;
      checked.add(normalized);
    }
    const parent = dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
  return undefined;
};

const runtimeDirectory = findRuntime();
if (!runtimeDirectory) {
  console.error("No existing Remotion runtime found. Pass --runtime=<path> or set REMOTION_RUNTIME.");
  process.exit(2);
}

const entryPoint = join(scriptDirectory, "src", "index.tsx");
const outputPath = resolve(outputArgument || join(scriptDirectory, "output", "shotcraft-knowledge-pilot-v1.mp4"));
const publicDirectory = join(scriptDirectory, "public");
mkdirSync(dirname(outputPath), { recursive: true });
mkdirSync(publicDirectory, { recursive: true });
const cliEntry = join(runtimeDirectory, "node_modules", "@remotion", "cli", "remotion-cli.js");
const renderArguments = [
  cliEntry,
  "render",
  entryPoint,
  "ShotcraftPilot-9x16",
  outputPath,
  "--codec=h264",
  "--crf=18",
  "--pixel-format=yuv420p",
  "--concurrency=1",
  `--public-dir=${publicDirectory}`,
];

console.log(JSON.stringify({ runtimeDirectory, entryPoint, publicDirectory, outputPath, concurrency: 1 }, null, 2));
const result = spawnSync(process.execPath, renderArguments, { cwd: runtimeDirectory, stdio: "inherit" });
process.exit(result.status ?? 1);
