import type { NextRequest } from "next/server";
import { requestPaperReport } from "@/lib/api/paper-report-server";
import { samplePaperCsv } from "@/lib/api/paper-report-preview";
import { readAuthConfig } from "@/lib/auth/config";
import { hasPreviewSession } from "@/lib/auth/preview-session";
import { sessionCookie } from "@/lib/auth/upstream";
import { parseReportPeriod, reportCsvFilename } from "@/lib/paper-reporting";

const privateHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

function fail(status: number, message: string) {
  return Response.json({ message }, { status, headers: privateHeaders });
}

function download(body: BodyInit | null) {
  return new Response(body, { headers: {
    ...privateHeaders,
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="${reportCsvFilename}"`,
  } });
}

export async function GET(request: NextRequest) {
  const config = readAuthConfig();
  if (config.mode === "unavailable") return fail(503, "Reports are temporarily unavailable.");

  const token = request.cookies.get(sessionCookie)?.value;
  if (config.mode === "staging" ? !token : !(await hasPreviewSession())) return fail(401, "Sign in to export paper trades.");

  const params = request.nextUrl.searchParams;
  const read = (key: string) => params.getAll(key).length > 1 ? params.getAll(key) : params.get(key) ?? undefined;
  const { period, error } = parseReportPeriod(read("from"), read("to"));
  if (error) return fail(400, error);
  if (config.mode === "preview") return download(samplePaperCsv(period));
  if (!token) return fail(401, "Sign in to export paper trades.");

  try {
    const response = await requestPaperReport(config.upstream, token, period, true);
    if (response.ok && /^text\/csv(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) return download(response.body);

    await response.body?.cancel();
    if (response.status === 401) return fail(401, "Sign in to export paper trades.");
    if (response.status === 400) return fail(400, "The report date range was rejected.");
  } catch {
    return fail(503, "Paper trades could not be exported. Try again shortly.");
  }
  return fail(503, "Paper trades could not be exported. Try again shortly.");
}
