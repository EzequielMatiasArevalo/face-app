"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { DetectionCanvas } from "@/components/detection-canvas";
import { ErrorBox, Spinner } from "@/components/ui";
import {
  adminDeletePhoto,
  adminDeleteRegistration,
  adminListPhotos,
  adminListUsers,
  adminSetRole,
  fetchBlob,
  fetchJson,
  type AdminPhoto,
  type AdminUser,
  type Detection,
  type PredictResult,
  type RegistrationPose,
} from "@/lib/api";

const POSES: Record<RegistrationPose, string> = {
  front_close: "frontal de cerca",
  front_far: "frontal de lejos",
  profile_left: "perfil izquierdo",
  profile_right: "perfil derecho",
};
const NO_DETECTIONS: Detection[] = [];

// Las imágenes se bajan con el token: como mucho 4 a la vez
const MAX_PARALLEL_DOWNLOADS = 4;
let activeDownloads = 0;
const waitingDownloads: (() => void)[] = [];
async function limited<T>(task: () => Promise<T>): Promise<T> {
  if (activeDownloads >= MAX_PARALLEL_DOWNLOADS) await new Promise<void>((resolve) => waitingDownloads.push(resolve));
  activeDownloads++;
  try {
    return await task();
  } finally {
    activeDownloads--;
    waitingDownloads.shift()?.();
  }
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

export function AdminView() {
  const { state, refreshMe } = useAuth();
  const me = state.status === "signedIn" ? state.me : null;
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const loadUsers = useCallback(() => {
    adminListUsers()
      .then((list) => {
        setUsers(list);
        setSelected((current) => (current ? (list.find((u) => u.uid === current.uid) ?? null) : null));
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  useEffect(() => {
    if (me?.role === "admin") loadUsers();
  }, [me?.role, loadUsers]);

  async function run(key: string, action: () => Promise<unknown>, affectsMe: boolean) {
    setBusy(key);
    setError(null);
    try {
      await action();
      loadUsers();
      if (affectsMe) await refreshMe(); // un cambio sobre la propia cuenta puede quitar el acceso a esta página
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (!me) return null;
  if (me.role !== "admin") {
    return (
      <main className="mx-auto w-full max-w-5xl p-6">
        <ErrorBox title="No tenés permisos de administrador." items={[]} />
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-4 sm:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Administración</h1>
        <p className="text-sm text-zinc-500">
          Usuarios, roles y todas las fotos guardadas en el bucket. Los administradores iniciales (ADMIN_EMAILS) no
          pueden perder el rol.
        </p>
      </div>
      {error && <ErrorBox title="La acción no se completó" items={[error]} />}

      <section className="card overflow-x-auto p-0">
        {!users ? (
          <div className="p-6">
            <Spinner label="Cargando usuarios…" />
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 text-xs uppercase text-zinc-500 dark:border-zinc-800">
              <tr>
                <th className="px-4 py-3">Usuario</th>
                <th className="px-4 py-3">Rol</th>
                <th className="px-4 py-3">Registro facial</th>
                <th className="px-4 py-3">Fotos</th>
                <th className="px-4 py-3">Última actividad</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {users.map((user) => {
                const isMe = user.uid === me.uid;
                return (
                  <tr key={user.uid} className={selected?.uid === user.uid ? "bg-zinc-50 dark:bg-zinc-900" : ""}>
                    <td className="px-4 py-3">
                      <div className="font-medium">
                        {user.name ?? user.email ?? user.uid}
                        {isMe && <span className="ml-2 text-xs text-zinc-500">(vos)</span>}
                      </div>
                      <div className="text-xs text-zinc-500">{user.has_account ? user.email : "identidad sin cuenta (registro previo al login)"}</div>
                    </td>
                    <td className="px-4 py-3">
                      {user.has_account ? (
                        <div className="flex flex-col items-start gap-1">
                          <span className={`rounded px-2 py-0.5 text-xs ${user.role === "admin" ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "bg-zinc-200 dark:bg-zinc-800"}`}>
                            {user.role}
                            {user.bootstrap_admin && " · inicial"}
                          </span>
                          {!user.bootstrap_admin && (
                            <button
                              className="text-xs text-zinc-500 underline hover:text-zinc-900 disabled:opacity-50 dark:hover:text-zinc-100"
                              disabled={busy !== null}
                              onClick={() => {
                                const role = user.role === "admin" ? "user" : "admin";
                                if (isMe && role === "user" && !window.confirm("Vas a quitarte el rol de administrador. ¿Seguir?")) return;
                                run(`role-${user.uid}`, () => adminSetRole(user.uid, role), isMe);
                              }}
                            >
                              {user.role === "admin" ? "Quitar admin" : "Hacer admin"}
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="text-zinc-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {user.face_registered ? (
                        <div className="flex flex-col items-start gap-1">
                          <span className="text-emerald-700 dark:text-emerald-400">Registrado</span>
                          <button
                            className="text-xs text-red-600 underline hover:text-red-800 disabled:opacity-50 dark:text-red-400"
                            disabled={busy !== null}
                            onClick={() => {
                              const who = user.name ?? user.email ?? user.uid;
                              if (!window.confirm(`¿Borrar el registro facial de ${who}? Va a tener que registrarse de nuevo.`)) return;
                              run(`reg-${user.uid}`, () => adminDeleteRegistration(user.uid), isMe);
                            }}
                          >
                            Borrar registro
                          </button>
                        </div>
                      ) : (
                        <span className="text-zinc-400">No</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {user.photo_count > 0 ? (
                        <button className="underline hover:text-zinc-600" onClick={() => setSelected(user)}>
                          Ver {user.photo_count}
                        </button>
                      ) : (
                        <span className="text-zinc-400">0</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-zinc-500">{formatDate(user.last_seen_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {selected && (
        <PhotoGallery
          key={selected.uid}
          user={selected}
          busy={busy !== null}
          onDelete={(photo) => run(`photo-${photo.id}`, () => adminDeletePhoto(photo.id), false)}
        />
      )}
    </main>
  );
}

function PhotoGallery({ user, busy, onDelete }: { user: AdminUser; busy: boolean; onDelete: (photo: AdminPhoto) => void }) {
  const [photos, setPhotos] = useState<AdminPhoto[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adminListPhotos(user.uid)
      .then((list) => !cancelled && setPhotos(list))
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [user.uid, user.photo_count]);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Fotos de {user.name ?? user.email ?? user.uid}</h2>
      {error && <ErrorBox title="No se pudieron cargar las fotos" items={[error]} />}
      {!photos && !error && <Spinner label="Cargando fotos…" />}
      {photos && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {photos.map((photo) => (
            <PhotoCard key={photo.id} photo={photo} busy={busy} onDelete={() => onDelete(photo)} />
          ))}
        </ul>
      )}
    </section>
  );
}

function photoLabel(photo: AdminPhoto): string {
  if (photo.kind === "registration") return `Registro · ${photo.pose ? POSES[photo.pose] : "?"}`;
  if (photo.kind === "prediction") return "Predicción";
  return "Sin clasificar";
}

function PhotoCard({ photo, busy, onDelete }: { photo: AdminPhoto; busy: boolean; onDelete: () => void }) {
  const [image, setImage] = useState<Blob | null>(null);
  const [result, setResult] = useState<PredictResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    limited(() =>
      Promise.all([
        fetchBlob(photo.url),
        photo.result_url ? fetchJson<PredictResult>(photo.result_url) : Promise.resolve(null),
      ]),
    )
      .then(([blob, prediction]) => {
        if (cancelled) return;
        setImage(blob);
        setResult(prediction);
      })
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [photo.url, photo.result_url]);

  // Los resultados migrados de antes de la detección de IA no traen ai_detection
  const aiGenerated = result?.ai_detection?.is_ai_generated ?? photo.ai_generated ?? false;
  const known = result?.detections.filter((d) => d.label !== "unknown") ?? [];

  return (
    <li className="card flex flex-col gap-3 p-4">
      {image ? (
        <DetectionCanvas image={image} detections={result?.detections ?? NO_DETECTIONS} aiGenerated={aiGenerated} />
      ) : error ? (
        <ErrorBox title="No se pudo cargar la imagen" items={[error]} />
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-xl bg-zinc-100 dark:bg-zinc-900">
          <Spinner />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{photoLabel(photo)}</span>
        {photo.active_registration && (
          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">registro vigente</span>
        )}
        {aiGenerated && <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-900 dark:bg-red-950 dark:text-red-200">IA</span>}
      </div>
      {result && !aiGenerated && (
        <p className="text-xs text-zinc-500">
          {result.detections.length} rostro(s)
          {known.length > 0 ? ` · ${[...new Set(known.map((d) => d.name))].join(", ")}` : " · ninguno reconocido"}
        </p>
      )}
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {formatDate(photo.created_at)}
          {photo.size_bytes ? ` · ${(photo.size_bytes / 1024).toFixed(0)} KB` : ""}
        </span>
        <button
          className="text-red-600 underline hover:text-red-800 disabled:opacity-50 dark:text-red-400"
          disabled={busy}
          onClick={() => window.confirm("¿Borrar esta foto (y su resultado) del bucket?") && onDelete()}
        >
          Borrar
        </button>
      </div>
    </li>
  );
}
