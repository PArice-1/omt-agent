import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OMT · 让想法轻盈发生",
  description: "一个简洁、清爽的本机 Agent 工作空间。",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
