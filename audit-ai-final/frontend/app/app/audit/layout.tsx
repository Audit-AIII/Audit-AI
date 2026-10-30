import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdditionsFrame } from "@/components/additions/AdditionsFrame";

export const metadata: Metadata = { title: "Audit log — Audit AI" };

export default function AuditLayout({ children }: { children: ReactNode }) {
  return <AdditionsFrame>{children}</AdditionsFrame>;
}
