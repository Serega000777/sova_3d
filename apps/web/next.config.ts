import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@physical-ai/contracts"],
  // Browser previews are exposed through short-lived Cloudflare quick tunnels.
  // Next.js blocks dev-only assets and the HMR websocket when their public
  // origin differs from localhost, which leaves the server-rendered loading
  // shell on screen. Keep this limited to Cloudflare's ephemeral preview
  // subdomains; production hosting does not use this development allowlist.
  allowedDevOrigins: ["*.trycloudflare.com"],
};

export default nextConfig;
