import { Suspense } from "react";
import { ReviewResult } from "./ReviewResult";

export default function ReviewStage() {
  return (
    <Suspense>
      <ReviewResult />
    </Suspense>
  );
}
