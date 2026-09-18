import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { TopBar } from "@/components/TopBar";

export const metadata: Metadata = {
  title: "Physical AI 3D",
  description: "Describe a physical object; get an editable, printable 3D model.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <TopBar />
          <main className="page">{children}</main>
        </div>
      </body>
    </html>
  );
}
