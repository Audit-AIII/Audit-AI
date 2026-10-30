import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdditionsFrame } from "@/components/additions/AdditionsFrame";

export const metadata: Metadata = { title: "Team — Audit AI" };

export default function TeamLayout({ children }: { children: ReactNode }) {
  return <AdditionsFrame>{children}</AdditionsFrame>;
}
