import type { Metadata } from "next";
import "@fontsource-variable/geist";
import { Providers } from "@/components/providers";
import { productName } from "@/lib/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: productName, template: `%s | ${productName}` },
  description: `${productName}’s simulated workspace for the Indian market.`,
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
