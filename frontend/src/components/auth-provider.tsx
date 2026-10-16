"use client";

import { GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut as firebaseSignOut, type User } from "firebase/auth";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { getMe, type Me } from "@/lib/api";
import { firebaseAuth } from "@/lib/firebase";

export type AuthState =
  | { status: "loading" }
  | { status: "signedOut" }
  | { status: "signedIn"; user: User; me: Me }
  | { status: "error"; user: User; error: string };

type AuthContextValue = {
  state: AuthState;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  /** Vuelve a pedir /me (por ejemplo, después de completar el registro del rostro). */
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

async function loadState(user: User | null): Promise<AuthState> {
  if (!user) return { status: "signedOut" };
  try {
    return { status: "signedIn", user, me: await getMe() };
  } catch (err) {
    return { status: "error", user, error: err instanceof Error ? err.message : String(err) };
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(
    () => onAuthStateChanged(firebaseAuth(), async (user) => setState(await loadState(user))),
    [],
  );

  const signInWithGoogle = useCallback(async () => {
    await signInWithPopup(firebaseAuth(), new GoogleAuthProvider());
  }, []);

  const signOut = useCallback(() => firebaseSignOut(firebaseAuth()), []);

  const refreshMe = useCallback(async () => {
    setState(await loadState(firebaseAuth().currentUser));
  }, []);

  return (
    <AuthContext value={{ state, signInWithGoogle, signOut, refreshMe }}>{children}</AuthContext>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
