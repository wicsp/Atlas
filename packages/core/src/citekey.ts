import { Citekey } from "@lumio/schema";
import { CoreError } from "./errors.ts";
import type { PaperMetadata } from "./paper-metadata.ts";

export interface CitekeyCandidate { kind: "candidate"; citekey: string; abbreviation: string }
export interface ConfirmedCitekey { kind: "confirmed"; citekey: string }
const STOP_WORDS = new Set(["a", "an", "the", "of", "for", "with", "and", "on", "in", "to", "at", "by", "from", "as", "is", "are"]);

function stem(metadata: PaperMetadata): string {
  const surname = metadata.firstAuthorFamily ?? metadata.authors[0]?.trim().split(/\s+/u).at(-1) ?? "";
  const ascii = surname.normalize("NFD").replace(/\p{M}/gu, "").replace(/[\s\-'’]/gu, "");
  const family = ascii.charAt(0).toUpperCase() + ascii.slice(1);
  return `${family}_${metadata.year}_`;
}

export function proposeCitekey(metadata: PaperMetadata): CitekeyCandidate | undefined {
  const colon = metadata.title.indexOf(":");
  const prefix = colon < 0 ? "" : metadata.title.slice(0, colon).trim();
  // A named method before ':' is preferable; otherwise use the first four content words.
  const abbreviation = prefix && !/\s/u.test(prefix) ? prefix : (metadata.title.match(/[\p{L}\p{N}]+/gu) ?? [])
    .filter((word) => !STOP_WORDS.has(word.toLowerCase())).slice(0, 4).map((word) => word.charAt(0).toUpperCase()).join("");
  const citekey = stem(metadata) + abbreviation;
  return Citekey.safeParse(citekey).success ? { kind: "candidate", citekey, abbreviation } : undefined;
}

/** Call only after the user accepts a candidate or supplies an explicit abbreviation. */
export function confirmCitekey(metadata: PaperMetadata, abbreviation: string): ConfirmedCitekey {
  const citekey = stem(metadata) + abbreviation;
  if (!Citekey.safeParse(citekey).success) {
    throw new CoreError("INVALID_CITEKEY", "citekey 不合法：作者姓须能转写为 ASCII，年份须为四位数，缩写只能含 ASCII 字母和数字");
  }
  return { kind: "confirmed", citekey };
}
