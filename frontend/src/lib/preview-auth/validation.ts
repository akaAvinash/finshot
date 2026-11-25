export function normalizeIndianMobile(value: string): string | null {
  const digits = value.trim().replace(/[ -]/g, "");
  const national = digits.replace(/^\+91/, "");
  return /^[6-9]\d{9}$/.test(national) ? national : null;
}
