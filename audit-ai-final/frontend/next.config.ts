import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // tokens.css lives in ../design (single source of truth), so the bundler root is the kit folder.
  turbopack: { root: path.join(__dirname, "..") },
  images: { formats: ["image/webp"] },
  devIndicators: false,
};

export default nextConfig;
