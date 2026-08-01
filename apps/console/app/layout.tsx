import type { Metadata } from "next";
import "vditor/dist/index.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atlas — 材料与项目写作",
  description: "Atlas 的私人材料处理、知识引用与 Markdown 项目写作空间。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
