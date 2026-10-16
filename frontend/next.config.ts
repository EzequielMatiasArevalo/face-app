import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

// La config de Firebase y la URL del backend salen de las variables genéricas del proyecto
// (exportadas en la shell, en ../.env o en .env.local; ver ../.env.example) y se incrustan en el
// bundle como NEXT_PUBLIC_* al compilar.
const firebaseProjectId = process.env.FIREBASE_PROJECT_ID || process.env.GCP_PROJECT_ID;
const publicEnv = {
  NEXT_PUBLIC_FIREBASE_API_KEY: process.env.FIREBASE_API_KEY,
  NEXT_PUBLIC_FIREBASE_APP_ID: process.env.FIREBASE_APP_ID,
  NEXT_PUBLIC_FIREBASE_PROJECT_ID: firebaseProjectId,
  NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN:
    process.env.FIREBASE_AUTH_DOMAIN || (firebaseProjectId ? `${firebaseProjectId}.firebaseapp.com` : undefined),
  NEXT_PUBLIC_BACKEND_URL: process.env.BACKEND_PUBLIC_URL || "http://localhost:8000",
  // Solo desarrollo: emulador de Firebase Auth
  NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST: process.env.FIREBASE_AUTH_EMULATOR_HOST,
};

export default function nextConfig(phase: string): NextConfig {
  const missing = [
    ...(firebaseProjectId ? [] : ["GCP_PROJECT_ID"]),
    ...["FIREBASE_API_KEY", "FIREBASE_APP_ID"].filter((name) => !process.env[name]),
  ];
  if (missing.length > 0) {
    const message = `Faltan variables del proyecto: ${missing.join(", ")} (ver .env.example en la raíz)`;
    if (phase === PHASE_PRODUCTION_BUILD) throw new Error(message);
    console.warn(message);
  }

  return {
    // Servidor mínimo en .next/standalone para la imagen de Docker
    output: "standalone",
    env: Object.fromEntries(
      Object.entries(publicEnv).filter((entry): entry is [string, string] => Boolean(entry[1])),
    ),
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
}
