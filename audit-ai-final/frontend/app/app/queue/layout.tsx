import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdditionsFrame } from "@/components/additions/AdditionsFrame";

export const metadata: Metadata = { title: "Review queue — Audit AI" };

export default function QueueLayout({ children }: { children: ReactNode }) {
  return <AdditionsFrame>{children}</AdditionsFrame>;
}
