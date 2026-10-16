"use client";

import { useEffect, useRef } from "react";

import type { Detection } from "@/lib/api";

const KNOWN = "#10b981";
const UNKNOWN = "#f59e0b";
const AI = "#dc2626";

/**
 * Dibuja la imagen con las cajas, el nombre y los 5 keypoints de cada rostro detectado.
 * Con `aiGenerated`, la marca como generada con IA (en ese caso no hay detecciones).
 */
export function DetectionCanvas({
  image,
  detections,
  aiGenerated = false,
}: {
  image: Blob;
  detections: Detection[];
  aiGenerated?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    createImageBitmap(image).then((bitmap) => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (cancelled || !canvas || !ctx) return;
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      ctx.drawImage(bitmap, 0, 0);

      // Grosor y texto proporcionales al ancho de la imagen, para que se vean parecidos al escalarla
      const line = Math.max(2, Math.round(bitmap.width / 300));
      ctx.lineWidth = line;
      const fontSize = Math.max(12, Math.round(bitmap.width / 28));
      const textHeight = fontSize + 8;
      ctx.font = `600 ${fontSize}px system-ui, sans-serif`;
      for (const d of detections) {
        const [x1, y1, x2, y2] = d.bbox;
        const color = d.label === "unknown" ? UNKNOWN : KNOWN;
        ctx.strokeStyle = color;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

        const text = `${d.label === "unknown" ? "Desconocido" : d.name} (${d.score.toFixed(2)})`;
        const labelWidth = ctx.measureText(text).width + 12;
        // Arriba de la caja si entra; si no, abajo. Corrida hacia adentro si se sale por la derecha
        const labelY = y1 - textHeight >= 0 ? y1 - textHeight : y2;
        const labelX = Math.max(0, Math.min(x1 - line / 2, bitmap.width - labelWidth));
        ctx.fillStyle = color;
        ctx.fillRect(labelX, labelY, labelWidth, textHeight);
        ctx.fillStyle = "#ffffff";
        ctx.fillText(text, labelX + 6, labelY + textHeight - 6);

        ctx.fillStyle = "#ffffff";
        for (const [kx, ky] of Object.values(d.keypoints)) {
          ctx.beginPath();
          ctx.arc(x1 + kx, y1 + ky, line * 1.5, 0, 2 * Math.PI);
          ctx.fill();
        }
      }

      if (aiGenerated) {
        ctx.fillStyle = "rgba(127, 29, 29, 0.35)";
        ctx.fillRect(0, 0, bitmap.width, bitmap.height);
        ctx.lineWidth = line * 3;
        ctx.strokeStyle = AI;
        ctx.strokeRect(line * 1.5, line * 1.5, bitmap.width - line * 3, bitmap.height - line * 3);
        const text = "GENERADA CON IA";
        const bannerHeight = textHeight * 1.6;
        const bannerWidth = Math.min(bitmap.width * 0.9, ctx.measureText(text).width * 1.25 + 24);
        ctx.fillStyle = AI;
        ctx.fillRect((bitmap.width - bannerWidth) / 2, (bitmap.height - bannerHeight) / 2, bannerWidth, bannerHeight);
        ctx.fillStyle = "#ffffff";
        ctx.font = `700 ${Math.round(fontSize * 1.25)}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, bitmap.width / 2, bitmap.height / 2, bannerWidth - 24);
      }
      bitmap.close();
    });
    return () => {
      cancelled = true;
    };
  }, [image, detections, aiGenerated]);

  return <canvas ref={canvasRef} className="h-auto max-h-[70vh] w-full rounded-xl bg-zinc-100 object-contain dark:bg-zinc-900" />;
}
