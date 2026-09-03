import type { Metadata } from "next";
import { Fraunces, Sora } from "next/font/google";
import "./globals.css";

export const dynamic = 'force-dynamic';

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
});

const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "GrantRx",
  description: "AI-powered scholarship matching for students",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${fraunces.variable} ${sora.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-surfaceBg text-textPrimary font-sans">
        {children}
      </body>
    </html>
  );
}
