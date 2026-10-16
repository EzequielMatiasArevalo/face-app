"use client";

import Link from "next/link";

import { useAuth } from "./auth-provider";

export function AppHeader({ showNav = true }: { showNav?: boolean }) {
  const { state, signOut } = useAuth();
  const me = state.status === "signedIn" ? state.me : null;

  return (
    <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="font-semibold">Reconocimiento facial</span>
          {showNav && (
            <nav className="text-sm text-zinc-600 dark:text-zinc-400">
              <Link href="/" className="hover:text-zinc-900 dark:hover:text-zinc-100">
                Reconocer
              </Link>
              {me?.role === "admin" && (
                <Link href="/admin" className="ml-4 hover:text-zinc-900 dark:hover:text-zinc-100">
                  Administración
                </Link>
              )}
            </nav>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm">
          {me && (
            <span className="hidden text-zinc-500 sm:inline">
              {me.name ?? me.email}
              {me.role === "admin" && <span className="ml-2 rounded bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-800">admin</span>}
            </span>
          )}
          <button className="btn-secondary px-3 py-1.5" onClick={signOut}>
            Cerrar sesión
          </button>
        </div>
      </div>
    </header>
  );
}
