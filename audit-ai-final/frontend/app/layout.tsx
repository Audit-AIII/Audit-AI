import type { Metadata, Viewport } from "next";
import "@fontsource-variable/gabarito";
import "@fontsource-variable/instrument-sans";
import "./globals.css";
import { ReliefDefs } from "@/components/layout/ReliefDefs";

export const metadata: Metadata = {
  title: "Audit AI — check first, publish sure",
  description:
    "Audit AI reviews every draft against your approved guidelines, facts and assets before it goes live. Each finding shows its source, and a person makes the final call.",
};

export const viewport: Viewport = {
  themeColor: "#d4b08f",
};

// Marks the document as JS-capable before paint so reveal start states never hide content without JS.
const jsFlag = `document.documentElement.classList.add("js")`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: jsFlag }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <ReliefDefs />
        {children}
      </body>
    </html>
  );
}
