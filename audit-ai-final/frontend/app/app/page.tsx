import { redirect } from "next/navigation";

/** /app opens on the dashboard. */
export default function AppIndex() {
  redirect("/app/insights");
}
