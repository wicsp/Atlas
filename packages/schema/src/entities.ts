import { z } from "zod";
import { Assignee, Base, Id, Timestamp, idOf, optional, withDefault } from "./common.ts";

/**
 * 论文 citekey：`<第一作者姓>_<年份>_<标题缩写>`，例如 `He_2020_LightGCN`。
 * 同时是文件名、笔记链接和 `\cite{}` 的 key。规则见 ADR 0004。
 */
export const CITEKEY_PATTERN = /^[A-Z][A-Za-z]*_[0-9]{4}_[A-Za-z0-9]+$/;
export const Citekey = z
  .string()
  .regex(CITEKEY_PATTERN, "citekey 必须是 姓_年份_缩写，例如 He_2020_LightGCN");

/** 论文笔记，文件位于 `library/papers/<citekey>.md`（ADR 0012）。 */
export const Paper = Base.extend({
  type: z.literal("paper"),
  id: idOf("pap"),
  citekey: Citekey,
  authors: z.array(z.string().min(1)).min(1),
  year: z.number().int(),
  venue: optional(z.string()),
  arxiv: optional(z.string()),
  doi: optional(z.string()),
  url: optional(z.url()),
  status: withDefault(z.enum(["to-read", "reading", "read"]), "to-read"),
});

/** 想法 / 灵感，可以链接论文和其他想法，最后被串进报告。 */
export const Idea = Base.extend({
  type: z.literal("idea"),
  id: idOf("idea"),
  status: withDefault(z.enum(["seed", "developing", "used", "dropped"]), "seed"),
  project: optional(idOf("prj")),
});

export const Project = Base.extend({
  type: z.literal("project"),
  id: idOf("prj"),
  status: withDefault(z.enum(["planning", "active", "paused", "done"]), "planning"),
  goal: optional(z.string()),
  repo: optional(z.string()).describe("关联代码仓库的路径或 URL"),
  deadline: optional(Timestamp),
});

export const Task = Base.extend({
  type: z.literal("task"),
  id: idOf("task"),
  status: withDefault(z.enum(["todo", "doing", "blocked", "review", "done"]), "todo"),
  project: optional(idOf("prj")),
  assignee: withDefault(Assignee, "human"),
  due: optional(Timestamp),
  job: optional(idOf("job")).describe("派给 AI 时对应的 job"),
});

export const Experiment = Base.extend({
  type: z.literal("experiment"),
  id: idOf("exp"),
  project: idOf("prj"),
  status: withDefault(z.enum(["planned", "running", "done", "failed"]), "planned"),
  hypothesis: optional(z.string()),
  config_ref: optional(z.string()).describe("配置文件路径或 git commit"),
  device: optional(z.string()),
  metrics: optional(z.record(z.string(), z.number())),
  artifacts: optional(z.array(z.string())),
});

/** 外部资料：网页、视频、播客、课程、书（ADR 0012 第 2 节），位于 `library/sources/`。 */
export const Source = Base.extend({
  type: z.literal("source"),
  id: idOf("src"),
  kind: withDefault(z.enum(["web", "video", "podcast", "course", "book"]), "web"),
  url: optional(z.url()),
  author: optional(z.string()),
  site: optional(z.string()),
  status: withDefault(z.enum(["to-read", "reading", "read"]), "to-read"),
});

const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:/;
const MEDIA_SCHEME = "media://";

/** 相对路径：非空，不以 `/` 开头，不含 `..` 段、反斜杠或其他 URL scheme。 */
function isRelativePath(path: string): boolean {
  if (!path || path.startsWith("/") || path.includes("\\") || SCHEME.test(path)) return false;
  return path.split("/").every((segment) => segment !== ".." && segment !== "");
}

/**
 * 媒体引用（ADR 0012 第 4 节）：vault 内的相对路径（如 `files/attachments/cover.png`），
 * 或 `media://<相对路径>`，由各设备在本机配置中解析到 vault 外的媒体根目录。
 */
export const MediaRef = z.string().refine(
  (ref) => isRelativePath(ref.startsWith(MEDIA_SCHEME) ? ref.slice(MEDIA_SCHEME.length) : ref),
  "媒体引用必须是 vault 内的相对路径或 media://<相对路径>，且不能含 ..",
);

export const POST_FORMATS = ["video", "gallery", "article", "text"] as const;
export const PostFormat = z.enum(POST_FORMATS);

/** 一次平台投放。`status`、`url`、`published_at`、`error` 由发布流程写入。 */
export const PostTarget = z.strictObject({
  platform: z.string().regex(/^[a-z0-9]+(-[a-z0-9]+)*$/, "platform 必须是 kebab-case，例如 bilibili"),
  format: optional(PostFormat).describe("覆盖 post 的 format"),
  media: optional(z.string()).describe("post.media 中的角色名"),
  schedule: optional(Timestamp),
  status: withDefault(z.enum(["pending", "scheduled", "published", "failed"]), "pending"),
  url: optional(z.url()),
  published_at: optional(Timestamp),
  error: optional(z.string()),
});

/** 发布内容（ADR 0012 第 4 节），位于 `create/posts/`。一篇 post = 一件要表达的事；每个平台一个 target。 */
export const Post = Base.extend({
  type: z.literal("post"),
  id: idOf("post"),
  format: PostFormat,
  status: withDefault(z.enum(["idea", "drafting", "ready", "done"]), "idea"),
  derived_from: withDefault(z.array(Id), []),
  media: withDefault(
    z.record(z.string().regex(/^[a-z][a-z0-9_-]*$/, "媒体角色名只能用小写字母、数字、- 和 _"), z.union([MediaRef, z.array(MediaRef)])),
    {},
  ),
  targets: withDefault(z.array(PostTarget), []),
}).superRefine((post, ctx) => {
  post.targets.forEach((target, i) => {
    if (target.media !== undefined && !Object.hasOwn(post.media, target.media)) {
      ctx.addIssue({ code: "custom", path: ["targets", i, "media"], message: `media 中没有角色 ${target.media}` });
    }
  });
});

const CARD_LIKE = /[0-9]{13,}/;

/** 去掉空格和连字符后含有 13 位以上连续数字，视为疑似完整卡号或账号。 */
function findCardLike(value: unknown, path: (string | number)[]): (string | number)[] | undefined {
  if (typeof value === "string" || (typeof value === "number" && Number.isInteger(value))) {
    return CARD_LIKE.test(String(value).replace(/[\s-]/g, "")) ? path : undefined;
  }
  if (Array.isArray(value)) {
    for (const [i, item] of value.entries()) {
      const found = findCardLike(item, [...path, i]);
      if (found) return found;
    }
  } else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      const found = findCardLike(item, [...path, key]);
      if (found) return found;
    }
  }
  return undefined;
}

const YEAR_MONTH = z.string().regex(/^[0-9]{4}-(0[1-9]|1[0-2])$/, "必须是 YYYY-MM");

/**
 * 资产：订阅、域名、卡、账户、服务器、保险、证件（ADR 0012 第 5 节），位于 `life/assets/`，属于私密实体。
 * 禁止存放完整卡号或账号、CVV、密码、密钥、余额、证件号码。
 */
export const Asset = Base.extend({
  type: z.literal("asset"),
  id: idOf("ast"),
  kind: z.enum(["subscription", "domain", "card", "bank-account", "account", "server", "insurance", "document", "other"]),
  provider: optional(z.string()),
  status: withDefault(z.enum(["active", "paused", "cancelled", "expired"]), "active"),
  cost: optional(z.number().nonnegative()).describe("每个周期的金额"),
  currency: optional(z.string().regex(/^[A-Z]{3}$/, "currency 必须是 ISO 4217 代码，例如 USD")),
  cycle: optional(z.union([z.enum(["monthly", "yearly", "once"]), z.number().int().positive()]))
    .describe("monthly、yearly、once，或周期天数"),
  renews_on: optional(z.iso.date()).describe("下次扣费日 YYYY-MM-DD"),
  expires: optional(z.union([z.iso.date(), YEAR_MONTH])).describe("YYYY-MM-DD 或 YYYY-MM"),
  auto_renew: optional(z.boolean()),
  paid_with: optional(idOf("ast")).describe("由哪张卡或哪个账户支付"),
  login: optional(z.string()),
  last4: optional(z.string().regex(/^[0-9]{4}$/, "last4 必须是带引号的 4 位数字，例如 \"4417\"")),
  vault_item: optional(z.string()).describe("密码管理器中对应条目的名称"),
  manage_url: optional(z.url()),
}).superRefine((asset, ctx) => {
  const path = findCardLike(asset, []);
  // 错误信息不回显该值
  if (path) ctx.addIssue({ code: "custom", path, message: "疑似完整卡号或账号，资产中只能记录后四位（last4）" });
});

/** 任意 vault 实体，按 `type` 字段区分。 */
export const Entity = z.discriminatedUnion("type", [Paper, Idea, Project, Task, Experiment, Source, Post, Asset]);

export type Paper = z.infer<typeof Paper>;
export type Idea = z.infer<typeof Idea>;
export type Project = z.infer<typeof Project>;
export type Task = z.infer<typeof Task>;
export type Experiment = z.infer<typeof Experiment>;
export type Source = z.infer<typeof Source>;
export type MediaRef = z.infer<typeof MediaRef>;
export type PostTarget = z.infer<typeof PostTarget>;
export type Post = z.infer<typeof Post>;
export type Asset = z.infer<typeof Asset>;
export type Entity = z.infer<typeof Entity>;
