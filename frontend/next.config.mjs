function serviceOrigin(environmentName, fallback) {
  const configured = String(process.env[environmentName] || fallback).trim();

  let url;
  try {
    url = new URL(configured);
  } catch {
    throw new Error(`${environmentName} must be an absolute http(s) URL.`);
  }

  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(`${environmentName} must use http or https.`);
  }

  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${environmentName} must contain only an origin, without a path, query, or fragment.`);
  }

  return url.origin;
}

const backendInternalUrl = serviceOrigin("BACKEND_INTERNAL_URL", "http://127.0.0.1:8000");
const agentInternalUrl = serviceOrigin("AGENT_INTERNAL_URL", "http://127.0.0.1:4173");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
];

if (process.env.NODE_ENV === "production") {
  securityHeaders.push({
    key: "Strict-Transport-Security",
    value: "max-age=31536000",
  });
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/api/agents/:path*",
        destination: `${agentInternalUrl}/api/agents/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${backendInternalUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
