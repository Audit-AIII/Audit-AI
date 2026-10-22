/** The five stages of a review, in order. The stage bar and each stage page read from here. */
export const STAGES = [
  { slug: "sources", n: "01", label: "Sources", hint: "Step 1 of 5: add the documents your content must follow." },
  { slug: "draft", n: "02", label: "Draft", hint: "Step 2 of 5: paste your text and choose where it will be posted." },
  { slug: "review", n: "03", label: "Review", hint: "Step 3 of 5: click a problem to see why it was flagged." },
  { slug: "decide", n: "04", label: "Decide", hint: "Step 4 of 5: choose what to do. Nothing changes until you say so." },
  { slug: "record", n: "05", label: "Record", hint: "Step 5 of 5: everything that happened is saved here." },
] as const;

export type StageSlug = (typeof STAGES)[number]["slug"];
