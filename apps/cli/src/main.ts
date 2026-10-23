#!/usr/bin/env bun
import { runCli } from "./cli.ts";

try { process.exitCode = await runCli(process.argv.slice(2)); }
catch (cause) {
  console.error(cause instanceof Error ? cause.message : "无法执行命令");
  process.exitCode = 1;
}
