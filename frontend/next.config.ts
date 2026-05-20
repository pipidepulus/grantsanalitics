/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // BACKEND_URL must be set per environment:
    //   local dev  → http://localhost:8000   (default)
    //   docker     → http://backend:8000     (set in docker-compose)
    //   production → https://api.yourdomain.com
    const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  httpAgentOptions: {
    keepAlive: true,
  },
  experimental: {
    proxyClientMaxBodySize: "25mb",
    proxyTimeout: 120_000,
  },
};

export default nextConfig;
