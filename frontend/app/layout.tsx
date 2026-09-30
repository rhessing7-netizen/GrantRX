import type { Metadata, Viewport } from "next";
import {
  Fraunces,
  Inter,
  Cormorant_Garamond,
  Caveat,
} from "next/font/google";
import "./globals.css";
import { SupportAssistantDrawer } from "@/components/SupportAssistantDrawer";
import { GoogleAnalytics } from "@/components/GoogleAnalytics";

export const dynamic = 'force-dynamic';

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#574AE2",
};

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const cormorant = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const caveat = Caveat({
  variable: "--font-caveat",
  subsets: ["latin"],
  weight: ["500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "EdFintia — Your prescription for education funding",
    template: "%s · EdFintia",
  },
  description:
    "EdFintia helps you discover legitimate scholarships, grants, tuition assistance, and other education-funding opportunities you may qualify for — without searching dozens of fragmented sources.",
  applicationName: "EdFintia",
  icons: {
    icon: [
      { url: "/brand/favicon.svg", type: "image/svg+xml" },
      { url: "/brand/favicon-32.png", sizes: "32x32" },
      { url: "/brand/favicon-16.png", sizes: "16x16" },
    ],
    shortcut: "/brand/favicon-32.png",
    apple: "/brand/apple-touch-icon.png",
  },
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
      className={`${fraunces.variable} ${inter.variable} ${cormorant.variable} ${caveat.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-text font-sans antialiased">
        <GoogleAnalytics />
        {children}
        <SupportAssistantDrawer />
      </body>
    </html>
  );
}
