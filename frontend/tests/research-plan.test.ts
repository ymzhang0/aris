import assert from "node:assert/strict";
import test from "node:test";

import { deriveResearchPlanFromDraft, normalizeResearchPlan } from "../src/lib/research-plan.ts";

test("normalizes an explicit scientific plan protocol", () => {
  const plan = normalizeResearchPlan({
    title: "Silicon EOS",
    objective: "Fit the equilibrium volume and bulk modulus.",
    stages: [{ id: "sweep", label: "Run volume sweep", status: "ready" }],
    assumptions: [{ label: "Functional", value: "PBE", source: "ai" }],
    outputs: ["EOS fit"],
  });

  assert.equal(plan?.title, "Silicon EOS");
  assert.equal(plan?.stages[0]?.status, "ready");
  assert.equal(plan?.assumptions[0]?.source, "ai");
});

test("derives a safe fallback plan from a batch Draft without domain keyword inference", () => {
  const plan = deriveResearchPlanFromDraft({
    process_label: "PwBaseWorkChain",
    inputs: {},
    primary_inputs: { protocol: { value: "moderate" } },
    meta: { draft: [{ inputs: {} }, { inputs: {} }], job_count: 2 },
  });

  assert.equal(plan.stages[1]?.label, "Review 2 linked runs");
  assert.equal(plan.assumptions[0]?.value, "moderate");
});
