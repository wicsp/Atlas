import { confirmCitekey, proposeCitekey, type ConfirmedCitekey, type PaperMetadata } from "@lumio/core";

export interface ConfirmOptions {
  abbreviation?: string;
  yes?: boolean;
  interactive: boolean;
  ask: (question: string) => Promise<string>;
  log: (message: string) => void;
}

export async function selectCitekey(metadata: PaperMetadata, options: ConfirmOptions): Promise<ConfirmedCitekey> {
  if (options.abbreviation !== undefined) return confirmCitekey(metadata, options.abbreviation);
  const candidate = proposeCitekey(metadata);
  if (options.yes) {
    if (!candidate) throw new Error("无法生成 citekey 候选，请使用 --abbr <缩写> 指定");
    return confirmCitekey(metadata, candidate.abbreviation);
  }
  if (!options.interactive) throw new Error("标准输入不是终端，请使用 --abbr <缩写> 或 --yes");
  // A new abbreviation cannot repair an untransliterable surname or invalid year.
  confirmCitekey(metadata, "A");
  while (true) {
    const prompt = candidate
      ? `citekey: ${candidate.citekey}\n回车确认，或输入新的缩写：`
      : "无法生成 citekey 候选，请输入缩写：";
    const value = (await options.ask(prompt)).trim();
    if (!value && candidate) return confirmCitekey(metadata, candidate.abbreviation);
    try { return confirmCitekey(metadata, value); }
    catch (cause) { options.log(cause instanceof Error ? cause.message : "缩写不合法，请重新输入"); }
  }
}
