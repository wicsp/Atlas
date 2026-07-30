"use client";

export function ConsoleNav({ current }: { current: "materials" | "projects" }) {
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
        className={current === "projects" ? "active" : ""}
        aria-current={current === "projects" ? "page" : undefined}
        href="/projects"
      >
        <span>02</span>项目写作
      </a>
    </nav>
  );
}
