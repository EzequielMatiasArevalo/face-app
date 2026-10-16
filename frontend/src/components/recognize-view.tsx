"use client";

import { useRef, useState } from "react";

import { DetectionCanvas } from "@/components/detection-canvas";
import { ImageInput } from "@/components/image-input";
import { ErrorBox, Spinner } from "@/components/ui";
import { fetchJson, startPredict, uploadImage, waitForJob, type Detection, type PredictResult } from "@/lib/api";

const MAX_PHOTOS = 10;
// Referencia estable: DetectionCanvas vuelve a dibujar solo cuando cambian sus detecciones
const NO_DETECTIONS: Detection[] = [];

type Photo = {
  id: number;
  image: Blob;
  status: "pending" | "processing" | "done" | "failed";
  result?: PredictResult;
  error?: string;
};

export function RecognizeView() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [running, setRunning] = useState(false);
  const nextId = useRef(0);
  const started = photos.some((photo) => photo.status !== "pending");

  function addPhoto(image: Blob) {
    const id = nextId.current++;
    setPhotos((prev) => (prev.length >= MAX_PHOTOS ? prev : [...prev, { id, image, status: "pending" }]));
  }

  function updatePhoto(id: number, patch: Partial<Photo>) {
    setPhotos((prev) => prev.map((photo) => (photo.id === id ? { ...photo, ...patch } : photo)));
  }

  /** Cada foto es un job independiente de /predict: los resultados aparecen a medida que terminan. */
  async function recognizePhoto(photo: Photo) {
    updatePhoto(photo.id, { status: "processing" });
    try {
      const jobId = await startPredict(await uploadImage(photo.image));
      const status = await waitForJob(jobId);
      if (status.status === "failed" || !status.artifact_url) {
        throw new Error(status.reason ?? "La predicción no devolvió resultado.");
      }
      updatePhoto(photo.id, { status: "done", result: await fetchJson<PredictResult>(status.artifact_url) });
    } catch (err) {
      updatePhoto(photo.id, { status: "failed", error: err instanceof Error ? err.message : String(err) });
    }
  }

  async function recognizeAll() {
    setRunning(true);
    await Promise.all(photos.map(recognizePhoto));
    setRunning(false);
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 p-4 sm:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Reconocer personas</h1>
        <p className="text-sm text-zinc-500">
          Agregá una o más fotos (hasta {MAX_PHOTOS}). Cada una se procesa por separado y se marcan todos los rostros
          detectados, incluidos los desconocidos.
        </p>
      </div>

      {!started ? (
        <section className="card flex flex-col gap-4">
          {photos.length < MAX_PHOTOS ? (
            <ImageInput onImage={addPhoto} multiple />
          ) : (
            <p className="text-sm text-zinc-500">Llegaste al máximo de {MAX_PHOTOS} fotos.</p>
          )}
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-zinc-500">
              {photos.length} de {MAX_PHOTOS} fotos
            </span>
            <button className="btn-primary" onClick={recognizeAll} disabled={photos.length === 0}>
              Reconocer {photos.length === 1 ? "1 foto" : `${photos.length} fotos`}
            </button>
          </div>
        </section>
      ) : (
        <Summary photos={photos} running={running} onReset={() => setPhotos([])} />
      )}

      {photos.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2">
          {photos.map((photo, index) => (
            <li key={photo.id} className="card flex flex-col gap-3 p-4">
              <DetectionCanvas
                image={photo.image}
                detections={photo.result?.detections ?? NO_DETECTIONS}
                aiGenerated={photo.result?.ai_detection.is_ai_generated ?? false}
              />
              <div className="flex min-h-6 items-center justify-between text-sm">
                <span className="font-medium">Foto {index + 1}</span>
                {photo.status === "pending" && (
                  <button
                    className="text-zinc-500 underline hover:text-zinc-900 dark:hover:text-zinc-100"
                    onClick={() => setPhotos((prev) => prev.filter((p) => p.id !== photo.id))}
                  >
                    Quitar
                  </button>
                )}
                {photo.status === "processing" && <Spinner label="Procesando…" />}
              </div>
              {photo.status === "failed" && <ErrorBox title="No se pudo procesar la foto" items={[photo.error ?? ""]} />}
              {photo.result && <PhotoResult result={photo.result} />}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function Summary({ photos, running, onReset }: { photos: Photo[]; running: boolean; onReset: () => void }) {
  const results = photos.flatMap((photo) => (photo.result ? [photo.result] : []));
  const faces = results.flatMap((result) => result.detections);
  const unknown = faces.filter((d) => d.label === "unknown").length;
  // Persona -> en cuántas fotos aparece
  const people = new Map<string, number>();
  for (const result of results) {
    for (const name of new Set(result.detections.filter((d) => d.label !== "unknown").map((d) => d.name))) {
      people.set(name, (people.get(name) ?? 0) + 1);
    }
  }
  const aiGenerated = results.filter((result) => result.ai_detection.is_ai_generated).length;
  const pending = photos.filter((photo) => photo.status === "pending" || photo.status === "processing").length;
  const failed = photos.filter((photo) => photo.status === "failed").length;

  return (
    <section className="card flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-medium">{results.length}</span> de {photos.length} fotos procesadas ·{" "}
          <span className="font-medium">{faces.length}</span> rostro(s) ·{" "}
          <span className="font-medium">{unknown}</span> desconocido(s)
          {aiGenerated > 0 && (
            <span className="text-red-600 dark:text-red-400"> · {aiGenerated} generada(s) con IA</span>
          )}
          {failed > 0 &&<span className="text-red-600 dark:text-red-400"> · {failed} con error</span>}
        </p>
        {running ? (
          <Spinner label={`Procesando ${pending} foto(s)…`} />
        ) : (
          <button className="btn-secondary" onClick={onReset}>
            Nueva predicción
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2 text-sm">
        {people.size === 0 ? (
          <span className="text-zinc-500">{running ? "Todavía no hay personas reconocidas." : "Ninguna persona registrada reconocida."}</span>
        ) : (
          [...people.entries()].map(([name, count]) => (
            <span key={name} className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
              {name} · {count === 1 ? "1 foto" : `${count} fotos`}
            </span>
          ))
        )}
      </div>
    </section>
  );
}

function PhotoResult({ result }: { result: PredictResult }) {
  const ai = result.ai_detection;
  if (ai.is_ai_generated) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
        <p className="font-medium">Imagen generada o alterada con IA: no se buscaron rostros.</p>
        <p className="mt-1 text-xs opacity-80">Motivo: {ai.evidence}</p>
      </div>
    );
  }
  return (
    <>
      <FaceList detections={result.detections} />
      {ai.score !== null && (
        <p className="text-xs text-zinc-500">Verificación de IA: no detectada (probabilidad {ai.score.toFixed(2)})</p>
      )}
    </>
  );
}

function FaceList({ detections }: { detections: Detection[] }) {
  if (detections.length === 0) return <p className="text-sm text-zinc-500">No se detectaron rostros.</p>;
  return (
    <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 text-sm dark:divide-zinc-800 dark:border-zinc-800">
      {detections.map((d, i) => (
        <li key={i} className="flex justify-between px-3 py-2">
          <span className={d.label === "unknown" ? "text-amber-700 dark:text-amber-400" : ""}>
            {d.label === "unknown" ? "Desconocido" : d.name}
          </span>
          <span className="font-mono text-zinc-500">similitud {d.score.toFixed(2)}</span>
        </li>
      ))}
    </ul>
  );
}
