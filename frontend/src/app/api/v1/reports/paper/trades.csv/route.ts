import type { NextRequest } from "next/server";
import { requestPaperReport } from "@/lib/api/paper-report-server";
import { apiProxyResponse } from "@/lib/api/proxy-response";
import { samplePaperCsv } from "@/lib/api/paper-report-preview";
import { readAuthConfig } from "@/lib/auth/config";
import { hasPreviewSession } from "@/lib/auth/preview-session";
import { sessionCookie } from "@/lib/auth/upstream";
import { parseReportPeriod, reportCsvFilename } from "@/lib/paper-reporting";

async function proxy(request: NextRequest) {
  const { fail, headers, requestId, wrongMethod, relay } = apiProxyResponse(request);
  if (request.method !== "GET") return wrongMethod(["GET"]);
  function download(body: BodyInit | null) {
    return new Response(body, { headers: headers({
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${reportCsvFilename}"`,
    }) });
  }
  const config = readAuthConfig();
  if (config.mode === "unavailable") return fail(503, "REPORTS_UNAVAILABLE", "Reports are temporarily unavailable.");

  const token = request.cookies.get(sessionCookie)?.value;
  if (config.mode === "staging" ? !token : !(await hasPreviewSession())) return fail(401, "UNAUTHENTICATED", "Sign in to export paper trades.");

  const params = request.nextUrl.searchParams;
  const read = (key: string) => params.getAll(key).length > 1 ? params.getAll(key) : params.get(key) ?? undefined;
  const { period, error } = parseReportPeriod(read("from"), read("to"));
  if (error) return fail(400, "INVALID_REQUEST", error);
  if (config.mode === "preview") return download(samplePaperCsv(period));
  if (!token) return fail(401, "UNAUTHENTICATED", "Sign in to export paper trades.");

  try {
    const response = await requestPaperReport(config.upstream, token, period, true, requestId);
    if (response.ok && /^text\/csv(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) return download(response.body);
    if (!response.ok && /^application\/json(?:\s*;|$)/i.test(response.headers.get("content-type") ?? "")) return await relay(response);

    await response.body?.cancel();
  } catch {}
  return fail(503, "REPORTS_UNAVAILABLE", "Paper trades could not be exported. Try again shortly.");
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
