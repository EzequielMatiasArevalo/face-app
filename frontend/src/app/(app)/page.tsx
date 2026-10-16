import { RecognizeView } from "@/components/recognize-view";

// El Gate de (app)/layout no renderiza la página hasta conocer la sesión (solo existe en el
// navegador), así que no se puede validar para navegación instantánea.
export const instant = false;

export default function RecognizePage() {
  return <RecognizeView />;
}
