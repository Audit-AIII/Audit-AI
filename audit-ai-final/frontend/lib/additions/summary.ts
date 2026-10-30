import type { FindingOut, SummaryCounts } from "../api/types";

/**
 * Reading the server's summary_counts (docs/governance.md 9.4). Pure, so qa/unit can test it.
 * A missing count is "–", never 0: nobody counted it.
 */
export const countText = (n: number | null | undefined) => (typeof n === "number" ? String(n) : "–");

/** The API's `tone` count is only these two style rules (risk_policy.TONE_RULE_TYPES), not a tone check. */
const STYLE_RULE_TYPES = ["all_caps_run", "emoji_run"];
export const isStyleRule = (f: Pick<FindingOut, "check_type" | "rule_type">) => f.check_type === "rule" && STYLE_RULE_TYPES.includes(f.rule_type ?? "");
export const toneCount = (counts?: SummaryCounts | null) => counts?.tone ?? 0;
