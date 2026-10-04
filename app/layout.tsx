import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flowstate — Traffic observatory",
  description: "Analyze public cameras, measure vehicle flow, and compare traffic by time of day.",
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
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
