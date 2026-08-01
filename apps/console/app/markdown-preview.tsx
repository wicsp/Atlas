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
