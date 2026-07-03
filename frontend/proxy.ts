import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (request.nextUrl.hostname !== "127.0.0.1") {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.hostname = "localhost";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
