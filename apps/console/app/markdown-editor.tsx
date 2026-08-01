"use client";

import { useEffect, useRef, useState } from "react";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minHeight?: number;
}

type VditorInstance = import("vditor").default;

/**
 * Markdown remains the controlled value. Vditor's IR mode only supplies the
 * Typora-like editing surface; Atlas never persists the editor's internal DOM.
 */
export function MarkdownEditor({
  value,
  onChange,
  placeholder = "开始写作…",
  minHeight = 430,
}: MarkdownEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<VditorInstance | null>(null);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    let disposed = false;
    let editor: VditorInstance | null = null;

    void import("vditor")
      .then(({ default: Vditor }) => {
        if (disposed || !hostRef.current) return;

        editor = new Vditor(hostRef.current, {
          value: valueRef.current,
          mode: "ir",
          lang: "zh_CN",
          minHeight,
          height: "auto",
          placeholder,
          cdn: "/vendor/vditor",
          cache: { enable: false },
          counter: { enable: true, type: "markdown" },
          resize: { enable: true, position: "bottom" },
          toolbar: [
            "headings",
            "bold",
            "italic",
            "strike",
            "|",
            "quote",
            "list",
            "ordered-list",
            "check",
            "|",
            "link",
            "table",
            "inline-code",
            "code",
            "|",
            "undo",
            "redo",
          ],
          toolbarConfig: { hide: false, pin: true },
          preview: {
            delay: 200,
            markdown: {
              codeBlockPreview: true,
              mathBlockPreview: true,
              sanitize: true,
            },
          },
          input: (markdown) => {
            valueRef.current = markdown;
            onChangeRef.current(markdown);
          },
          after: () => {
            if (disposed) {
              editor?.destroy();
              return;
            }
            editorRef.current = editor;
            const latest = valueRef.current;
            if (editor?.getValue() !== latest) editor?.setValue(latest, true);
          },
        });
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });

    return () => {
      disposed = true;
      if (editorRef.current === editor) editorRef.current = null;
      editor?.destroy();
    };
  }, [minHeight, placeholder]);

  useEffect(() => {
    const editor = editorRef.current;
    if (editor && editor.getValue() !== value) editor.setValue(value, true);
  }, [value]);

  if (failed) {
    return (
      <textarea
        className="knowledge-body"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        spellCheck
      />
    );
  }

  return <div className="atlas-markdown-editor" ref={hostRef} />;
}
