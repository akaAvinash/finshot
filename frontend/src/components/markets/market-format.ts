const countFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const shortCountFormat = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 2 });
const sessionTimeFormat = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const updatedFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatVolume(volume: number | null, compact = false) {
  return volume === null ? "—" : (compact ? shortCountFormat : countFormat).format(volume);
}

export function formatSessionTime(asOf: string) {
  return sessionTimeFormat.format(new Date(asOf));
}

export function formatMarketTime(asOf: string) {
  return `${updatedFormat.format(new Date(asOf))} IST`;
}
