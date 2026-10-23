import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdditionsFrame } from "@/components/additions/AdditionsFrame";

export const metadata: Metadata = { title: "Correction editor — Audit AI" };

export default function ReviewEditLayout({ children }: { children: ReactNode }) {
  return <AdditionsFrame>{children}</AdditionsFrame>;
}
