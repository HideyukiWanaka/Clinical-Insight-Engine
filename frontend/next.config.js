/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",   // Required for Docker prod stage
  reactStrictMode: true,
  
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.BACKEND_INTERNAL_URL || "http://backend:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
