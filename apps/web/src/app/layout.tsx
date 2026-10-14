import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { TopBar } from "@/components/TopBar";

export const metadata: Metadata = {
  title: "Sova 3D",
  description: "Создавайте, сканируйте и точно редактируйте 3D-модели.",
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
