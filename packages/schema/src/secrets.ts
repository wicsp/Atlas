/**
 * 疑似银行卡号检测（ADR 0012"卡号防护"）。
 *
 * 用在三处：asset 的 schema 校验、Hub 自动提交前、建索引前。
 * 判定：一段数字的写法像卡号，并且通过 Luhn 校验。
 *   - 连续 13–19 位数字；
 *   - 或按常见卡号格式用同一种分隔符（空格或连字符）分组：4-4-4-4（可再跟 1–3 位）、4-6-5。
 * 只认这几种写法，是为了不把日期、电话、ISBN 之类误判成卡号。
 *
 * 任何调用方都不得把命中的数字写进错误信息或日志。
 */

const CARD_LAYOUTS: RegExp[] = [
  /(?<![\d-])\d{13,19}(?![\d-])/g,
  /(?<![\d-])\d{4}([ -])\d{4}\1\d{4}\1\d{4}(?:\1\d{1,3})?(?![\d-])/g,
  /(?<![\d-])\d{4}([ -])\d{6}\1\d{5}(?![\d-])/g,
];

/** Luhn 校验：所有银行卡号都满足，随机数字串约只有十分之一满足。 */
export function luhnValid(digits: string): boolean {
  if (!/^\d+$/.test(digits)) return false;
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    let d = digits.charCodeAt(digits.length - 1 - i) - 48;
    if (i % 2 === 1) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0;
}

/** 一段文本中是否含有疑似卡号。 */
export function textContainsCardNumber(text: string): boolean {
  for (const layout of CARD_LAYOUTS) {
    for (const match of text.matchAll(layout)) {
      const digits = match[0].replace(/[ -]/g, "");
      if (digits.length >= 13 && digits.length <= 19 && luhnValid(digits)) return true;
    }
  }
  return false;
}

/** 任意值（含嵌套的对象、数组，以及 YAML 解析出的数字）中是否含有疑似卡号。 */
export function containsCardNumber(value: unknown): boolean {
  if (typeof value === "string") return textContainsCardNumber(value);
  if (typeof value === "number" || typeof value === "bigint") {
    // YAML 中不加引号的长数字会被解析成数字；超出安全整数范围时精度可能丢失，
    // 但只要还是 13–19 位整数，就按原样检查。
    return Number.isInteger(value as number) || typeof value === "bigint"
      ? textContainsCardNumber(value.toLocaleString("en-US", { useGrouping: false }))
      : false;
  }
  if (Array.isArray(value)) return value.some(containsCardNumber);
  if (value && typeof value === "object") {
    return Object.entries(value).some(([key, v]) => textContainsCardNumber(key) || containsCardNumber(v));
  }
  return false;
}
