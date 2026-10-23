import { StageHead } from "@/components/app/Stage";
import { DraftForm } from "./DraftForm";

export default function DraftStage() {
  return (
    <>
      <StageHead title="Draft" status="Not checked yet" />
      <DraftForm />
    </>
  );
}
