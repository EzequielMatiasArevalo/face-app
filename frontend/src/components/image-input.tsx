"use client";

import { useEffect, useRef, useState } from "react";

type Source = "camera" | "file";

/**
 * Elegir una imagen sacando una foto con la cámara o subiendo un archivo.
 * Con `multiple`, se pueden elegir varios archivos a la vez (onImage se llama una vez por archivo).
 */
export function ImageInput({ onImage, multiple = false }: { onImage: (image: Blob) => void; multiple?: boolean }) {
  const [source, setSource] = useState<Source>("camera");

  return (
    <div className="flex flex-col gap-3">
      <div className="inline-flex self-start rounded-lg border border-zinc-200 p-1 text-sm dark:border-zinc-800">
        {(["camera", "file"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setSource(option)}
            className={`rounded-md px-3 py-1.5 ${
              source === option ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 dark:text-zinc-400"
            }`}
          >
            {option === "camera" ? "Cámara" : "Subir archivo"}
          </button>
        ))}
      </div>
      {source === "camera" ? (
        <CameraCapture onCapture={onImage} />
      ) : (
        <FilePicker onFile={onImage} multiple={multiple} />
      )}
    </div>
  );
}

function FilePicker({ onFile, multiple }: { onFile: (file: Blob) => void; multiple: boolean }) {
  return (
    <label className="flex aspect-video cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-zinc-300 text-sm text-zinc-500 hover:border-zinc-400 dark:border-zinc-700">
      <span className="font-medium text-zinc-700 dark:text-zinc-300">
        {multiple ? "Elegí una o más imágenes" : "Elegí una imagen"}
      </span>
      <span>JPG, PNG o WebP</span>
      <input
        type="file"
        accept="image/*"
        multiple={multiple}
        className="sr-only"
        onChange={(event) => {
          Array.from(event.target.files ?? []).forEach((file) => onFile(file));
          event.target.value = "";
        }}
      />
    </label>
  );
}

const UNSUPPORTED = "Este navegador no permite usar la cámara. Subí un archivo.";

function CameraCapture({ onCapture }: { onCapture: (image: Blob) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    const media = navigator.mediaDevices;
    const request = media?.getUserMedia
      ? media.getUserMedia({ video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      : Promise.reject(new Error(UNSUPPORTED));
    request
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch((err) =>
        setError(
          err instanceof Error && err.message === UNSUPPORTED
            ? UNSUPPORTED
            : "No se pudo acceder a la cámara. Revisá los permisos del navegador o subí un archivo.",
        ),
      );
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    // Se guarda la imagen sin espejar: la vista previa espejada es solo para que sea natural posar
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob((blob) => blob && onCapture(blob), "image/jpeg", 0.92);
  }

  if (error) {
    return <p className="rounded-xl bg-zinc-100 p-6 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">{error}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        onLoadedData={() => setReady(true)}
        className="aspect-video w-full -scale-x-100 rounded-xl bg-zinc-900 object-contain"
      />
      <button type="button" className="btn-primary self-center" disabled={!ready} onClick={capture}>
        Sacar foto
      </button>
    </div>
  );
}
