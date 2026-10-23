import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdditionsFrame } from "@/components/additions/AdditionsFrame";

export const metadata: Metadata = { title: "Evidence coverage — Audit AI" };

export default function CoverageLayout({ children }: { children: ReactNode }) {
  return <AdditionsFrame>{children}</AdditionsFrame>;
}
