"use client";

export function ConsoleNav({ current }: { current: "materials" | "knowledge" | "projects" }) {
  return (
    <nav className="workspace-nav" aria-label="Atlas 工作空间">
      <a
        className={current === "materials" ? "active" : ""}
        aria-current={current === "materials" ? "page" : undefined}
        href="/materials"
      >
        <span>01</span>材料
      </a>
      <a
        className={current === "knowledge" ? "active" : ""}
        aria-current={current === "knowledge" ? "page" : undefined}
        href="/knowledge"
      >
        <span>02</span>知识库
      </a>
      <a
        className={current === "projects" ? "active" : ""}
        aria-current={current === "projects" ? "page" : undefined}
        href="/projects"
      >
        <span>03</span>项目写作
      </a>
    </nav>
  );
}
