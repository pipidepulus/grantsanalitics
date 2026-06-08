/**
 * Route Handler for /api/chat/stream
 *
 * Next.js rewrites() proxy buffers SSE responses before forwarding them to
 * the browser, so streaming tokens never appear in real time. This Route
 * Handler bypasses that by piping upstream.body (a ReadableStream) directly
 * to the browser without any intermediate buffering.
 *
 * Route Handlers take priority over rewrites, so this file intercepts
 * POST /api/chat/stream before next.config.ts rewrites can touch it.
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const upstream = await fetch(`${backendUrl}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const error = await upstream
      .json()
      .catch(() => ({ detail: upstream.statusText }));
    return Response.json(error, { status: upstream.status });
  }

  // Pipe upstream.body (ReadableStream) straight to the browser.
  // No buffering occurs — each SSE chunk is forwarded as it arrives.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
