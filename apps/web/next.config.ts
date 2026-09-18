import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@physical-ai/contracts"],
};

export default nextConfig;
