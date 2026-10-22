import { redirect } from "next/navigation";

/** /app opens on the first stage. */
export default function AppIndex() {
  redirect("/app/sources");
}
