import { AppHeader } from "@/components/app-header";
import { Gate } from "@/components/gate";

/** Toda sección bajo (app) exige sesión iniciada y rostro registrado. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Gate mode="app">
      <AppHeader />
      {children}
    </Gate>
  );
}
