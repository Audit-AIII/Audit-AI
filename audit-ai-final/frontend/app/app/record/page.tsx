import { Suspense } from "react";
import { RecordPanel } from "./RecordPanel";

export default function RecordStage() {
  return (
    <Suspense>
      <RecordPanel />
    </Suspense>
  );
}
