"use client";

import { FirebaseError } from "firebase/app";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Gate } from "@/components/gate";
import { ErrorBox } from "@/components/ui";

// Cerrar el popup o abrir otro no es un error para mostrar
const IGNORED_ERRORS = new Set(["auth/popup-closed-by-user", "auth/cancelled-popup-request"]);

export default function LoginPage() {
  return (
    <Gate mode="guest">
      <Login />
    </Gate>
  );
}

function Login() {
  const { signInWithGoogle } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSignIn() {
    setPending(true);
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      if (!(err instanceof FirebaseError && IGNORED_ERRORS.has(err.code))) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <div className="card flex w-full max-w-sm flex-col gap-6 text-center">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-semibold">Reconocimiento facial</h1>
          <p className="text-sm text-zinc-500">
            Iniciá sesión para continuar. La primera vez vas a tener que registrar tu rostro.
          </p>
        </div>
        <button className="btn-primary w-full py-2.5" onClick={handleSignIn} disabled={pending}>
          <GoogleIcon />
          {pending ? "Abriendo Google…" : "Continuar con Google"}
        </button>
        {error && <ErrorBox title="No se pudo iniciar sesión" items={[error]} />}
      </div>
    </main>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.5-5.2 3.5-8.8Z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
    </svg>
  );
}
