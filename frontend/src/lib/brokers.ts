import type { BrokerAccount, BrokerId, BrokerScope, BrokerStatus } from "@/lib/api/broker-types";

export const brokerNames: Record<BrokerId, string> = { zerodha: "Zerodha", fyers: "Fyers" };

export const brokerScopeNames: Record<BrokerScope, string> = {
  profile_read: "Read account profile",
  holdings_read: "Read holdings",
  orders_read: "Read order history",
};

export function getBrokerStatus(account: BrokerAccount | null, asOf: string): BrokerStatus {
  if (!account) return "disconnected";
  return Date.parse(account.expiresAt) <= Date.parse(asOf) ? "expired" : "connected";
}

const brokerDate = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatBrokerTime(time: string) {
  return `${brokerDate.format(new Date(time))} IST`;
}
