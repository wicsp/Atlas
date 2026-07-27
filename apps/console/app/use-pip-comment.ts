"use client";

import { useCallback, useState } from "react";

interface PipState {
  window: Window;
  resourceId: string;
}

/** Escape text for safe embedding in an inline <script> / HTML document. */
function jsStringLiteral(value: string): string {
  return JSON.stringify(value);
}

/**
 * Manages a Document Picture-in-Picture window that hosts the "我的评论"
 * textarea.  The caller wires up BroadcastChannel listeners in the main page.
 */
export function usePictureInPictureComment() {
  const [pip, setPip] = useState<PipState | null>(null);

  const openPip = useCallback(
    async (
      resourceId: string,
      resourceTitle: string,
      draft: string,
    ): Promise<boolean> => {
      // Gracefully degrade when the API is unavailable (e.g. non-Chromium, mobile).
      if (!("documentPictureInPicture" in window)) {
        return false;
      }

      // If the same resource is already open, just focus the existing PiP window.
      if (pip && pip.resourceId === resourceId && !pip.window.closed) {
        pip.window.focus();
        return true;
      }

      // Close a previous PiP for a different resource.
      if (pip && !pip.window.closed) {
        pip.window.close();
      }

      try {
        const pipWindow = await window.documentPictureInPicture.requestWindow({
          width: 400,
          height: 350,
        });

        const titleJson = jsStringLiteral(resourceTitle);
        const draftJson = jsStringLiteral(draft);
        const idJson = jsStringLiteral(resourceId);

        pipWindow.document.write(/* html */ `
          <!DOCTYPE html>
          <html lang="zh-CN">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width,initial-scale=1" />
            <title>Atlas · 我的评论</title>
            <style>
              * { box-sizing: border-box; margin: 0; padding: 0; }
              body {
                display: flex; flex-direction: column; height: 100vh; overflow: hidden;
                font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #fbfaf6; color: #17221e;
              }
              .pip-header {
                display: flex; align-items: center; gap: 0.55rem;
                padding: 0.6rem 0.8rem;
                border-bottom: 1px solid #d4d0c5;
                background: linear-gradient(90deg, rgba(23,77,58,0.06), transparent 45%);
                flex-shrink: 0;
              }
              .pip-header .glyph {
                width: 24px; height: 24px; display: grid; place-items: center;
                border: 1px solid #17221e; border-radius: 50%;
                font-family: Iowan Old Style, Baskerville, Georgia, serif; font-size: 0.75rem;
                flex-shrink: 0;
              }
              .pip-header strong {
                font-size: 0.78rem; font-weight: 650;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
              }
              .pip-header small {
                color: #667069; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 0.58rem;
              }
              textarea {
                flex: 1; width: 100%; padding: 0.75rem;
                border: 0; resize: none; outline: none;
                background: transparent; color: #17221e;
                font: inherit; font-size: 0.8rem; line-height: 1.6;
              }
              textarea:focus { background: #fffef9; }
              .pip-footer {
                display: flex; justify-content: space-between; align-items: center;
                padding: 0.5rem 0.8rem;
                border-top: 1px solid #d4d0c5; background: #dce8df;
                flex-shrink: 0;
              }
              .pip-footer small { color: #667069; font-size: 0.62rem; }
              .pip-footer button {
                min-height: 32px; padding: 0 0.7rem;
                border: 1px solid #174d3a; border-radius: 2px;
                background: #174d3a; color: white;
                cursor: pointer; font-size: 0.7rem; font-weight: 650;
              }
              .pip-footer button:hover { background: #0f3e2d; }
              .pip-footer button:disabled { opacity: 0.48; cursor: not-allowed; }
            </style>
          </head>
          <body>
            <div class="pip-header">
              <span class="glyph">A</span>
              <div>
                <strong>${titleJson.slice(1, -1)}</strong>
                <small>我的评论</small>
              </div>
            </div>
            <textarea id="ta" placeholder="在这里写评论…支持 Markdown。">${draftJson.slice(1, -1)}</textarea>
            <div class="pip-footer">
              <small id="status">草稿中</small>
              <button id="save">保存评论</button>
            </div>
            <script>
              var bc = new BroadcastChannel("atlas-pip-comment");
              var ta = document.getElementById("ta");
              var statusEl = document.getElementById("status");
              var saveBtn = document.getElementById("save");
              var RESOURCE_ID = ${idJson};
              var syncTimer;

              ta.addEventListener("input", function () {
                statusEl.textContent = "草稿中";
                clearTimeout(syncTimer);
                syncTimer = setTimeout(function () {
                  bc.postMessage({ type: "draft", resourceId: RESOURCE_ID, text: ta.value });
                  statusEl.textContent = "已同步";
                  setTimeout(function () {
                    if (statusEl.textContent === "已同步") statusEl.textContent = "草稿中";
                  }, 1200);
                }, 400);
              });

              saveBtn.addEventListener("click", function () {
                saveBtn.disabled = true;
                saveBtn.textContent = "保存中…";
                bc.postMessage({ type: "save", resourceId: RESOURCE_ID, text: ta.value });
              });

              bc.addEventListener("message", function (event) {
                var data = event.data;
                if (data.type === "saved" && data.resourceId === RESOURCE_ID) {
                  saveBtn.textContent = "已保存 ✓";
                  statusEl.textContent = "评论已保存到 Atlas";
                  saveBtn.style.background = "#667069";
                  saveBtn.style.borderColor = "#667069";
                  setTimeout(function () { window.close(); }, 1500);
                } else if (data.type === "save-error" && data.resourceId === RESOURCE_ID) {
                  saveBtn.disabled = false;
                  saveBtn.textContent = "保存评论";
                  statusEl.textContent = data.message || "保存失败";
                  statusEl.style.color = "#a74839";
                }
              });

              window.addEventListener("pagehide", function () {
                bc.postMessage({ type: "draft", resourceId: RESOURCE_ID, text: ta.value });
                bc.close();
              });
            </script>
          </body>
          </html>
        `);

        setPip({ window: pipWindow, resourceId });

        pipWindow.addEventListener("pagehide", () => setPip(null));

        return true;
      } catch {
        return false;
      }
    },
    [pip],
  );

  const closePip = useCallback(() => {
    if (pip && !pip.window.closed) pip.window.close();
    setPip(null);
  }, [pip]);

  return { pip, openPip, closePip } as const;
}
