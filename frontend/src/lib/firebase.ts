import { getApp, getApps, initializeApp } from "firebase/app";
import { connectAuthEmulator, getAuth, type Auth } from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

// Solo para desarrollo/pruebas: usar el emulador de Auth en lugar de los usuarios reales del proyecto
const authEmulatorHost = process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST;

/**
 * Firebase se inicializa a demanda y solo desde efectos o handlers: con Cache Components
 * Next.js también prerenderiza los Client Components en el servidor.
 */
export function firebaseAuth(): Auth {
  const auth = getAuth(getApps().length ? getApp() : initializeApp(firebaseConfig));
  if (authEmulatorHost && !auth.emulatorConfig) {
    connectAuthEmulator(auth, `http://${authEmulatorHost}`, { disableWarnings: true });
  }
  return auth;
}
