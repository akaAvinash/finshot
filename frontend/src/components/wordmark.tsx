import Image from "next/image";
import { cn } from "@/lib/utils";

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={cn("relative block overflow-hidden rounded-lg bg-[#050505]", compact ? "h-8 w-[7.5rem]" : "h-12 w-[10.5rem]")}>
      <Image
        src="/brand/tradeo_approved_logo.png"
        alt="Tradeo"
        width={2172}
        height={724}
        loading="eager"
        sizes={compact ? "172px" : "226px"}
        className={cn("absolute max-w-none", compact ? "top-[-12px] left-[-28px] w-[172px]" : "top-[-14px] left-[-31px] w-[226px]")}
      />
    </span>
  );
}
