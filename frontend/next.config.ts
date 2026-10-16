import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Servidor mínimo en .next/standalone para la imagen de Docker
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
