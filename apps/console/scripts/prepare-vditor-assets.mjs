import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const consoleRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(consoleRoot, "node_modules/vditor/dist");
const targetRoot = resolve(consoleRoot, "public/vendor/vditor/dist");

await rm(targetRoot, { force: true, recursive: true });
await mkdir(targetRoot, { recursive: true });

await Promise.all(
  ["css", "images", "js"].map((directory) =>
    cp(resolve(sourceRoot, directory), resolve(targetRoot, directory), { recursive: true }),
  ),
);
