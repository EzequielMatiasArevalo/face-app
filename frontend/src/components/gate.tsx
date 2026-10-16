"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth, type AuthState } from "./auth-provider";
import { Spinner } from "./ui";

/**
 * guest: solo sin sesión (login).
 * registration: con sesión y SIN rostro registrado (registro).
 * app: con sesión y rostro registrado (el resto de la app).
 */
export type GateMode = "guest" | "registration" | "app";

/** Adónde tiene que ir el usuario, o null si puede ver esta sección. */
function redirectFor(state: AuthState, mode: GateMode): string | null {
  if (state.status === "loading" || state.status === "error") return null;
  if (state.status === "signedOut") return mode === "guest" ? null : "/login";
  const registered = state.me.face_registered;
  if (mode === "guest") return registered ? "/" : "/registro";
  if (mode === "registration") return registered ? "/" : null;
  return registered ? null : "/registro";
}

export function Gate({ mode, children }: { mode: GateMode; children: ReactNode }) {
  const { state, refreshMe, signOut } = useAuth();
  const router = useRouter();
  const target = redirectFor(state, mode);

  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);

  if (state.status === "error") {
    return (
      <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
        <h1 className="text-lg font-semibold">No se pudo contactar al backend</h1>
        <p className="text-sm text-zinc-500">{state.error}</p>
        <div className="flex gap-3">
          <button className="btn-primary" onClick={refreshMe}>
            Reintentar
          </button>
          <button className="btn-secondary" onClick={signOut}>
            Cerrar sesión
          </button>
        </div>
      </div>
    );
  }
  // Hasta saber si hay sesión y si el rostro está registrado no se muestra nada protegido
  if (state.status === "loading" || target) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Spinner label="Cargando…" />
      </div>
    );
  }
  return children;
}
