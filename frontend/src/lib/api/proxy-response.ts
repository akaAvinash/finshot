import "server-only";

const idPattern = /^[A-Za-z0-9._-]{1,64}$/;
const baseHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

export function apiProxyResponse(request: Request, cacheControl = baseHeaders["Cache-Control"]) {
  const supplied = request.headers.get("X-Request-ID");
  const clientId = supplied && idPattern.test(supplied) ? supplied : undefined;
  const requestId = clientId ?? crypto.randomUUID();

  function headers(extra?: HeadersInit) {
    const result = new Headers(extra);
    for (const [name, value] of Object.entries(baseHeaders)) result.set(name, value);
    result.set("Cache-Control", cacheControl);
    result.set("X-Request-ID", requestId);
    return result;
  }

  function fail(status: number, code: string, message: string, extra?: HeadersInit) {
    return Response.json({ code, message, requestId }, { status, headers: headers(extra) });
  }

  function wrongMethod(methods: readonly string[]) {
    return fail(405, "METHOD_NOT_ALLOWED", "This method is not allowed for the API endpoint.", { Allow: methods.join(", ") });
  }

  async function relay(upstream: Response, cookies: readonly string[] = []) {
    const output = headers();
    const upstreamId = upstream.headers.get("X-Request-ID");
    const id = clientId ?? (upstreamId && idPattern.test(upstreamId) ? upstreamId : requestId);
    output.set("X-Request-ID", id);
    for (const name of ["content-type", "retry-after", "allow"]) {
      const value = upstream.headers.get(name);
      if (value) output.set(name, value);
    }
    for (const cookie of cookies) output.append("Set-Cookie", cookie);
    if (upstream.ok) return new Response(upstream.body, { status: upstream.status, headers: output });

    const body = await upstream.json().catch(() => null);
    if (!body || typeof body.code !== "string" || typeof body.message !== "string") {
      return fail(502, "INTERNAL_ERROR", "The staging API returned an unexpected response.");
    }
    return Response.json({ ...body, requestId: id }, { status: upstream.status, headers: output });
  }

  return { requestId, headers, fail, wrongMethod, relay };
}
