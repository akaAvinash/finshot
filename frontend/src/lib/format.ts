const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const prices = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("en-IN", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});
const snapshotDate = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});

export function formatInr(value: number, signed = false) {
  return `${signed && value > 0 ? "+" : ""}${inr.format(value)}`;
}

export function formatPrice(value: number) {
  return prices.format(value);
}

export function formatPercent(value: number) {
  return percent.format(value / 100);
}

export function formatSnapshotDate(value: string) {
  return snapshotDate.format(new Date(value));
}
