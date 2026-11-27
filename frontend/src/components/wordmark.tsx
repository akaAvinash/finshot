import Image from "next/image";
import { productName } from "@/lib/brand";
import { cn } from "@/lib/utils";

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span role="img" aria-label={productName} className={cn("inline-flex items-center leading-none", compact ? "gap-1.5" : "gap-2.5")}>
      <span aria-hidden className={cn("relative shrink-0 overflow-hidden rounded-full bg-[#050505]", compact ? "size-8" : "size-10")}>
        <Image
          src="/brand/tradeo_approved_logo.png"
          alt=""
          width={2172}
          height={724}
          loading="eager"
          sizes={compact ? "172px" : "216px"}
          className={cn("absolute max-w-none", compact ? "top-[-12px] left-[-28px] w-[172px]" : "top-[-16px] left-[-37px] w-[216px]")}
        />
      </span>
      <span aria-hidden className={cn("font-black italic tracking-[-0.075em] text-foreground", compact ? "text-xl" : "text-[1.8rem]")}>
        Fin<span className="text-accent-foreground">Shot</span>
      </span>
    </span>
  );
}
