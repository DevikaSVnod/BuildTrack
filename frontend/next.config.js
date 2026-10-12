/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    domains: ["localhost"],
  },
  // Only affects `next build` output (used by the Docker image); `next dev` is unaffected.
  output: "standalone",
};

module.exports = nextConfig;
