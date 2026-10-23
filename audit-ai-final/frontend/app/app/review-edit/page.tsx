import { Suspense } from "react";
import { Editor } from "./Editor";

export default function ReviewEditPage() {
  return (
    <Suspense>
      <Editor />
    </Suspense>
  );
}
