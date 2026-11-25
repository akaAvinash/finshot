import "server-only";

export async function readBoundedBody(request: Request, limit: number) {
  const stream = request.body?.getReader();
  if (!stream) return "";
  const buffer = new Uint8Array(limit);
  let length = 0;
  try {
    for (;;) {
      const { done, value } = await stream.read();
      if (done) return new TextDecoder().decode(buffer.subarray(0, length));
      if (length + value.byteLength > limit) {
        await stream.cancel();
        return null;
      }
      buffer.set(value, length);
      length += value.byteLength;
    }
  } finally {
    stream.releaseLock();
  }
}
