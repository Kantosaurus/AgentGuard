import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the tracing root to this app so Next stops picking up an unrelated
  // C:\Users\wooai\package-lock.json on the dev machine.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
