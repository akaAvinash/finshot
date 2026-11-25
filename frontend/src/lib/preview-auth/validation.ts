export function normalizeIndianMobile(value: string): string | null {
  const digits = value.trim().replace(/[ -]/g, "");
  const national = digits.replace(/^\+91/, "");
  return /^[6-9]\d{9}$/.test(national) ? national : null;
}

export function normalizeEmail(value: string): string | null {
  const email = value.trim().toLowerCase();
  if (email.length > 254) return null;
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? email : null;
}
