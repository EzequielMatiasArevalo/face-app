"use client";

import { useEffect, useRef, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { useAuth } from "@/components/auth-provider";
import { Gate } from "@/components/gate";
import { ImageInput } from "@/components/image-input";
import { ErrorBox, Spinner } from "@/components/ui";
import { ApiError, startRegistration, uploadImage, waitForJob, type RegistrationPose } from "@/lib/api";

const STEPS: { pose: RegistrationPose; title: string; hint: string }[] = [
  {
    pose: "front_close",
    title: "Frontal de cerca",
    hint: "Mirá a la cámara con la cara cerca: tu rostro tiene que ocupar buena parte de la imagen.",
  },
  {
    pose: "front_far",
    title: "Frontal de lejos",
    hint: "Alejate de la cámara y seguí mirando de frente. Tu cara tiene que verse claramente más chica que en la foto anterior.",
  },
  {
    pose: "profile_left",
    title: "Perfil izquierdo",
    hint: "Girá la cabeza hacia un costado hasta quedar de perfil (cerca de 90°).",
  },
  {
    pose: "profile_right",
    title: "Perfil derecho",
    hint: "Ahora girá la cabeza hacia el otro costado, también de perfil.",
  },
];
const REVIEW_STEP = STEPS.length;

type Shot = { blob: Blob; url: string };
type Shots = Partial<Record<RegistrationPose, Shot>>;

export default function RegistroPage() {
  return (
    <Gate mode="registration">
      <AppHeader showNav={false} />
      <RegistrationWizard />
    </Gate>
  );
}

/** "ValueError: Registro rechazado: a; b" -> ["A", "B"] */
function parseProblems(reason: string | null): string[] {
  if (!reason) return ["El registro falló sin detalle."];
  const text = reason.replace(/^\w+: /, "").replace(/^Registro rechazado: /, "");
  return text.split("; ").map((item) => item.charAt(0).toUpperCase() + item.slice(1));
}

function RegistrationWizard() {
  const { state, refreshMe } = useAuth();
  const [shots, setShots] = useState<Shots>({});
  const [step, setStep] = useState(0);
  // Al repetir una foto desde la revisión, después de sacarla se vuelve a la revisión
  const [fromReview, setFromReview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [problems, setProblems] = useState<string[] | null>(null);

  const shotsRef = useRef(shots);
  useEffect(() => {
    shotsRef.current = shots;
  }, [shots]);
  useEffect(() => () => Object.values(shotsRef.current).forEach((shot) => URL.revokeObjectURL(shot.url)), []);

  function setShot(pose: RegistrationPose, blob: Blob | null) {
    const previous = shots[pose];
    if (previous) URL.revokeObjectURL(previous.url);
    const next = { ...shots };
    if (blob) next[pose] = { blob, url: URL.createObjectURL(blob) };
    else delete next[pose];
    setShots(next);
  }

  function retakeFromReview(index: number) {
    setShot(STEPS[index].pose, null);
    setFromReview(true);
    setStep(index);
  }

  async function submit() {
    setSubmitting(true);
    setProblems(null);
    try {
      const uploaded = await Promise.all(STEPS.map(async ({ pose }) => [pose, await uploadImage(shots[pose]!.blob)]));
      const jobId = await startRegistration(Object.fromEntries(uploaded));
      const result = await waitForJob(jobId);
      if (result.status === "done") {
        await refreshMe(); // con el rostro registrado, el Gate redirige a la app
        return;
      }
      setProblems(parseProblems(result.reason));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await refreshMe();
        return;
      }
      setProblems([err instanceof Error ? err.message : String(err)]);
    } finally {
      setSubmitting(false);
    }
  }

  const name = state.status === "signedIn" ? (state.me.name ?? state.me.email) : null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 p-4 sm:p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Registrá tu rostro{name ? `, ${name}` : ""}</h1>
        <p className="text-sm text-zinc-500">
          Antes de usar la app necesitamos 4 fotos tuyas, con un solo rostro en cada una. Vamos a validar la pose,
          la distancia y que sean de la misma persona.
        </p>
      </div>

      <ol className="grid grid-cols-4 gap-2 text-xs">
        {STEPS.map(({ pose, title }, index) => (
          <li
            key={pose}
            className={`rounded-lg border px-2 py-2 text-center ${
              index === step
                ? "border-zinc-900 font-medium dark:border-zinc-100"
                : shots[pose]
                  ? "border-emerald-500 text-emerald-700 dark:text-emerald-400"
                  : "border-zinc-200 text-zinc-500 dark:border-zinc-800"
            }`}
          >
            {shots[pose] ? "✓ " : `${index + 1}. `}
            {title}
          </li>
        ))}
      </ol>

      {step < REVIEW_STEP ? (
        <CaptureStep
          key={STEPS[step].pose}
          index={step}
          shot={shots[STEPS[step].pose]}
          onImage={(blob) => setShot(STEPS[step].pose, blob)}
          onRetake={() => setShot(STEPS[step].pose, null)}
          onBack={step > 0 && !fromReview ? () => setStep(step - 1) : undefined}
          nextLabel={fromReview || step === REVIEW_STEP - 1 ? "Revisar fotos" : "Siguiente"}
          onNext={() => {
            setStep(fromReview ? REVIEW_STEP : step + 1);
            setFromReview(false);
          }}
        />
      ) : (
        <section className="card flex flex-col gap-5">
          <h2 className="text-lg font-semibold">Revisá tus fotos</h2>
          <div className="grid grid-cols-2 gap-4">
            {STEPS.map(({ pose, title }, index) => (
              <figure key={pose} className="flex flex-col gap-2">
                {/* eslint-disable-next-line @next/next/no-img-element -- object URL local */}
                <img src={shots[pose]?.url} alt={title} className="aspect-video w-full rounded-xl bg-zinc-100 object-contain dark:bg-zinc-900" />
                <figcaption className="flex items-center justify-between text-sm">
                  {title}
                  <button className="text-zinc-500 underline hover:text-zinc-900 dark:hover:text-zinc-100" disabled={submitting} onClick={() => retakeFromReview(index)}>
                    Repetir
                  </button>
                </figcaption>
              </figure>
            ))}
          </div>
          {problems && (
            <ErrorBox title="El registro no se completó:" items={problems} />
          )}
          <div className="flex items-center justify-end gap-3">
            {submitting && <Spinner label="Validando tus fotos…" />}
            <button className="btn-primary" onClick={submit} disabled={submitting}>
              Completar registro
            </button>
          </div>
        </section>
      )}
    </main>
  );
}

function CaptureStep({
  index,
  shot,
  onImage,
  onRetake,
  onBack,
  onNext,
  nextLabel,
}: {
  index: number;
  shot: Shot | undefined;
  onImage: (blob: Blob) => void;
  onRetake: () => void;
  onBack?: () => void;
  onNext: () => void;
  nextLabel: string;
}) {
  const { title, hint } = STEPS[index];
  return (
    <section className="card flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">
          {index + 1}. {title}
        </h2>
        <p className="text-sm text-zinc-500">{hint}</p>
      </div>
      {shot ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- object URL local */}
          <img src={shot.url} alt={title} className="aspect-video w-full rounded-xl bg-zinc-100 object-contain dark:bg-zinc-900" />
          <div className="flex justify-end gap-3">
            <button className="btn-secondary" onClick={onRetake}>
              Repetir
            </button>
            <button className="btn-primary" onClick={onNext}>
              {nextLabel}
            </button>
          </div>
        </>
      ) : (
        <ImageInput onImage={onImage} />
      )}
      {onBack && !shot && (
        <button className="self-start text-sm text-zinc-500 underline hover:text-zinc-900 dark:hover:text-zinc-100" onClick={onBack}>
          Volver al paso anterior
        </button>
      )}
    </section>
  );
}
