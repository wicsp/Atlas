import { readFile } from "node:fs/promises";
import type { PaperFetcher } from "../src/paper-source.ts";

export const paperFixture = (name: string): Promise<string> => readFile(new URL(`../../../fixtures/papers/${name}`, import.meta.url), "utf8");

/** No fallback to the network, including in the child CLI process's preload. */
export const fixtureFetcher: PaperFetcher = async (url) => {
  const parsed = new URL(url);
  if (parsed.origin === "https://export.arxiv.org") {
    return new Response(await paperFixture(`${parsed.searchParams.get("id_list")}.xml`));
  }
  if (parsed.origin === "https://arxiv.org" && parsed.pathname.startsWith("/bibtex/")) {
    return new Response(await paperFixture(`${parsed.pathname.slice(8)}.bib`));
  }
  if (parsed.origin === "https://api.crossref.org") return new Response(await paperFixture("crossref-lightgcn.json"));
  if (parsed.origin === "https://doi.org") return new Response(await paperFixture("crossref-lightgcn.bib"));
  throw new Error(`Network is disabled in this test: ${url}`);
};
