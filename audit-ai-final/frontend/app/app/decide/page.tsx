import { Suspense } from "react";
import { DecidePanel } from "./DecidePanel";

export default function DecideStage() {
  return (
    <Suspense>
      <DecidePanel />
    </Suspense>
  );
}
