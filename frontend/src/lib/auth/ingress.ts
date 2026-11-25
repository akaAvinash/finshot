import "server-only";

import { timingSafeEqual } from "node:crypto";
import { isIP } from "node:net";

export function getTrustedClientIp(headers: Headers, ingressToken: string) {
  const address = headers.get("x-tradeo-client-ip");
  const token = headers.get("x-tradeo-ingress-token");
  if (!address || address.includes("%") || !isIP(address) || !token) return null;

  const expected = Buffer.from(ingressToken);
  const supplied = Buffer.from(token);
  if (expected.length !== supplied.length || !timingSafeEqual(expected, supplied)) return null;
  return address;
}
