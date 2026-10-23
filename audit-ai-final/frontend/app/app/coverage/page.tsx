import { Suspense } from "react";
import { Coverage } from "./Coverage";

export default function CoveragePage() {
  return (
    <Suspense>
      <Coverage />
    </Suspense>
  );
}
