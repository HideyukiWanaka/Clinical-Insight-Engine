// app/api/health/route.ts — Frontend health check used by Docker healthcheck
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    service: "frontend",
    version: "1.0.0",
    timestamp: new Date().toISOString(),
  });
}
