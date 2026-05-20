import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pipidepulus AI - Generador de Proyectos de Alto Impacto",
  description:
    "Plataforma AI para generación y optimización de propuestas para convocatorias de financiamiento",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className="antialiased">{children}</body>
    </html>
  );
}
