import Image from "next/image";
import { productName } from "@/lib/brand";
import { cn } from "@/lib/utils";

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span role="img" aria-label={productName} className={cn("inline-flex items-center leading-none", compact ? "gap-1.5" : "gap-2.5")}>
      <span aria-hidden className={cn("shrink-0 rounded-lg bg-[#151619] dark:bg-transparent", compact ? "size-8" : "size-10")}>
        <Image
          src="/brand/finshot-gold-fin.png"
          alt=""
          width={160}
          height={160}
          loading="eager"
          unoptimized
          className="size-full"
        />
      </span>
      <span aria-hidden className={cn("font-bold tracking-[-0.055em] text-foreground", compact ? "text-xl" : "text-[1.8rem]")}>
        {productName}
      </span>
    </span>
  );
}
