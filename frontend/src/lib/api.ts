import { firebaseAuth } from "./firebase";

export const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export type Role = "user" | "admin";

export type Me = {
  uid: string;
  email: string | null;
  name: string | null;
  role: Role;
  face_registered: boolean;
};

export type AdminUser = {
  /** uid de Firebase, o la etiqueta de una identidad registrada sin cuenta */
  uid: string;
  email: string | null;
  name: string | null;
  role: Role | null;
  has_account: boolean;
  /** Admin definido en ADMIN_EMAILS: no se le puede quitar el rol */
  bootstrap_admin: boolean;
  face_registered: boolean;
  photo_count: number;
  last_seen_at: string | null;
};

export type AdminPhoto = {
  id: string;
  uid: string;
  url: string;
  created_at: string;
  kind: "registration" | "prediction" | null;
  pose: RegistrationPose | null;
  active_registration: boolean;
  result_url: string | null;
  ai_generated: boolean | null;
  size_bytes: number | null;
};

export type RegistrationPose = "front_close" | "front_far" | "profile_left" | "profile_right";

export type JobStatus = {
  status: "done" | "inProgress" | "failed";
  link: string;
  reason: string | null;
  artifact_url: string | null;
  source_image_url: string | null;
};

export type Detection = {
  bbox: [number, number, number, number];
  /** k0..k4 relativos a la esquina superior izquierda de la caja */
  keypoints: Record<string, [number, number]>;
  label: string;
  name: string;
  score: number;
};

export type AIDetection = {
  is_ai_generated: boolean;
  /** metadata: marcas de procedencia (C2PA/IPTC, Stable Diffusion, ComfyUI); model: clasificador */
  method: "metadata" | "model";
  /** Probabilidad de IA según el modelo (null si decidieron los metadatos) */
  score: number | null;
  evidence: string;
};

export type PredictResult = {
  source_path: string;
  ai_detection: AIDetection;
  /** Vacío si la imagen es generada con IA: no se corre la detección de rostros */
  detections: Detection[];
  detected_people: string[];
};

/** Todas las llamadas al backend llevan el ID token de Firebase del usuario actual. */
async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const user = firebaseAuth().currentUser;
  if (!user) throw new ApiError(401, "No hay una sesión iniciada.");
  const token = await user.getIdToken();
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // respuesta sin JSON: queda el statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res;
}

async function postJob(path: string, payload: unknown): Promise<string> {
  const res = await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await res.json()).job_id;
}

export async function getMe(): Promise<Me> {
  return (await request("/me")).json();
}

/** Sube una imagen y devuelve la ruta en el servidor que esperan /insert y /predict. */
export async function uploadImage(image: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", image, "foto.jpg");
  return (await (await request("/upload", { method: "POST", body: form })).json()).path;
}

export function startRegistration(images: Record<RegistrationPose, string>): Promise<string> {
  return postJob("/insert", { images });
}

export function startPredict(sourcePath: string): Promise<string> {
  return postJob("/predict", { source_path: sourcePath, source_type: "image" });
}

export async function waitForJob(jobId: string, intervalMs = 1000, timeoutMs = 120_000): Promise<JobStatus> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const status: JobStatus = await (await request(`/status/${jobId}`)).json();
    if (status.status !== "inProgress") return status;
    if (Date.now() > deadline) throw new ApiError(408, "El procesamiento está tardando demasiado.");
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/** Los archivos de /files/... requieren el token, así que no sirven como <img src> directo. */
export async function fetchJson<T>(url: string): Promise<T> {
  return (await request(url)).json();
}

export async function fetchBlob(url: string): Promise<Blob> {
  return (await request(url)).blob();
}

// --- administración (el backend responde 403 si el usuario no es admin) ---

export async function adminListUsers(): Promise<AdminUser[]> {
  return (await request("/admin/users")).json();
}

export async function adminListPhotos(uid: string): Promise<AdminPhoto[]> {
  return (await request(`/admin/users/${encodeURIComponent(uid)}/photos`)).json();
}

export async function adminSetRole(uid: string, role: Role): Promise<AdminUser> {
  const res = await request(`/admin/users/${encodeURIComponent(uid)}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  return res.json();
}

export async function adminDeletePhoto(photoId: string): Promise<void> {
  await request(`/admin/photos/${encodeURIComponent(photoId)}`, { method: "DELETE" });
}

export async function adminDeleteRegistration(uid: string): Promise<void> {
  await request(`/admin/users/${encodeURIComponent(uid)}/registration`, { method: "DELETE" });
}
