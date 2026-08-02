"use client";

import { useEffect, useRef } from "react";

interface MarkdownPreviewProps {
  markdown: string;
  className?: string;
}

export function MarkdownPreview({ markdown, className = "" }: MarkdownPreviewProps) {
  const previewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview) {
      return;
    }

    let cancelled = false;
    preview.textContent = markdown;

    void import("vditor")
      .then(({ default: Vditor }) => {
        if (cancelled) {
          return;
        }

        return Vditor.preview(preview, markdown, {
          mode: "light",
          lang: "zh_CN",
          cdn: "/vendor/vditor",
          anchor: 1,
          hljs: {
            enable: true,
            lineNumber: false,
            style: "github",
          },
          math: {
            engine: "KaTeX",
            inlineDigit: true,
          },
          markdown: {
            codeBlockPreview: true,
            footnotes: true,
            mathBlockPreview: true,
            sanitize: true,
          },
        });
      })
      .catch(() => {
        if (!cancelled) {
          preview.textContent = markdown;
        }
      });

    return () => {
      cancelled = true;
    };
  }, [markdown]);

  return (
    <div
      ref={previewRef}
      className={`resource-content vditor-reset ${className}`.trim()}
      aria-label="渲染后的 Resource 正文"
    >
      {markdown}
    </div>
  );
}

export function PaperReadingBrief({ markdown }: { markdown: string }) {
  const evidenceHeading = "## 证据与细节";
  const evidenceIndex = markdown.indexOf(evidenceHeading);
  if (evidenceIndex < 0) {
    return <MarkdownPreview markdown={markdown} className="paper-reading-brief" />;
  }

  const visible = markdown.slice(0, evidenceIndex).trim();
  const evidence = markdown.slice(evidenceIndex).trim();
  return (
    <div className="paper-reading-brief">
      <MarkdownPreview markdown={visible} className="paper-brief-visible" />
      <details className="paper-brief-evidence">
        <summary>查看完整证据、实验设置与核查位置</summary>
        <MarkdownPreview markdown={evidence} className="paper-brief-detail" />
      </details>
    </div>
  );
}
