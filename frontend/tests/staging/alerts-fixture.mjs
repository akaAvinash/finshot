const root = "/api/v1/alerts";
const stamp = "2026-11-25T10:00:00Z";

function item(id, source, severity, title, kind, link = null) {
  return { id, source, severity, title, kind, environment: source === "security" ? null : source === "brokers" ? "DEMO" : "PAPER",
    message: `${title} in the staging test account.`, occurredAt: stamp, createdAt: stamp, acknowledgedAt: null, link };
}

export function createAlertsFixture() {
  const rows = [
    item("paper-halt", "paper", "critical", "Paper engine halted", "PAPER_ENGINE_HALTED"),
    item("paper-cancel", "paper", "warning", "Paper order cancelled", "PAPER_ORDER_CANCELLED"),
    item("sign-in", "security", "info", "New sign-in", "NEW_SIGN_IN"),
    ...Array.from({ length: 24 }, (_, index) => item(`replay-${index}`, "paper", "info", `Paper replay ${index + 1} finished`, "PAPER_REPLAY_FINISHED")),
    item("broker-expiry", "brokers", "critical", "Demo broker connection expired", "BROKER_CONNECTION_EXPIRED", {
      kind: "broker-connection", id: "35fbccd0-ab7c-4edc-85c0-a23abf2cd7fd",
    }),
  ];
  let inApp = { critical: true, warning: true, info: true };
  let updatedAt = null;
  const channels = ["email", "sms", "push"].map((channel) => ({ channel, available: false, enabled: false }));
  return {
    list(params) {
      const status = params.get("status") ?? "all";
      const severity = params.getAll("severity");
      const source = params.getAll("source");
      const cursor = params.get("cursor");
      const signature = JSON.stringify([status, severity, source, inApp]);
      let start = 0;
      if (cursor) {
        try {
          const decoded = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
          if (decoded.signature !== signature || !Number.isSafeInteger(decoded.start) || decoded.start < 1 || decoded.start >= rows.length) return null;
          start = decoded.start;
        } catch {
          return null;
        }
      }
      const allowed = rows.map((row, index) => ({ row, index })).filter(({ row }) => inApp[row.severity]);
      const unread = { total: 0, critical: 0, warning: 0, info: 0 };
      for (const { row } of allowed) {
        if (row.acknowledgedAt === null) {
          unread[row.severity]++;
          unread.total++;
        }
      }
      const eligible = allowed.filter(({ row, index }) => index >= start &&
        (status !== "unread" || row.acknowledgedAt === null) && (!severity.length || severity.includes(row.severity)) &&
        (!source.length || source.includes(row.source)));
      const limit = Number(params.get("limit") ?? 25);
      const page = eligible.slice(0, limit);
      const next = eligible.length > limit ? Buffer.from(JSON.stringify({ signature, start: page.at(-1).index + 1 })).toString("base64url") : null;
      return { asOf: stamp, items: page.map(({ row }) => row), nextCursor: next, unread };
    },
    acknowledge(id) {
      const row = rows.find((candidate) => candidate.id === id);
      if (!row) return null;
      row.acknowledgedAt ??= stamp;
      return row;
    },
    preferences() { return { inApp, channels, updatedAt }; },
    save(body) {
      if (!body || Object.keys(body).join() !== "inApp" || !body.inApp ||
          Object.keys(body.inApp).sort().join() !== "info,warning" ||
          typeof body.inApp.warning !== "boolean" || typeof body.inApp.info !== "boolean") return null;
      inApp = { critical: true, warning: body.inApp.warning, info: body.inApp.info };
      updatedAt = stamp;
      return { inApp, channels, updatedAt };
    },
  };
}

export function isAlertsFixtureRequest(path) {
  return path === root || path.startsWith(`${root}/`);
}
