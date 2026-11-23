import type { Metadata } from "next";
import "@fontsource-variable/geist";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Tradeo", template: "%s | Tradeo" },
  description: "Tradeo’s simulated workspace for the Indian market.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
