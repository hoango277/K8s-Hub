import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { QueryProvider } from "@/providers/query-provider";
import "./globals.css";

// The pairing of console.groq.com, the user's reference (docs/ke-hoach/he-mau-giao-dien.md):
// Inter for UI text — sturdy strokes and a tall x-height keep 13–14px text legible on
// Windows, where the earlier Plus Jakarta Sans read as thin and faint — Space Grotesk for
// headings and group labels, JetBrains Mono for code and resource names. All three carry
// the Vietnamese subset: the assistant answers in Vietnamese when asked in Vietnamese, and
// a font without those marks falls back glyph by glyph. next/font self-hosts the files,
// so the browser never calls Google Fonts.
const sans = Inter({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-inter",
  display: "swap",
});
const display = Space_Grotesk({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-space-grotesk",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin", "latin-ext", "vietnamese"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "K8s Hub",
  description: "AI-assisted Kubernetes operations platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
