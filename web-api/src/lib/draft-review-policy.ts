export type DraftReviewPolicyInput = {
  name?: string | null;
  review_required?: boolean | null;
  qa_review_required?: boolean | null;
  qa_gate?: Record<string, unknown> | null;
  diagnostic_artifact?: Record<string, unknown> | null;
  approval_blocked_reasons?: unknown;
};

export type DraftReviewPolicy = {
  review_required: boolean;
  approval_blocked: boolean;
  approval_blocked_reasons: string[];
  approval_policy_version: 'qa-review-gate-v1';
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function hasBlockingDefect(defects: unknown): boolean {
  return Array.isArray(defects) && defects.some((item) => {
    const d = asRecord(item);
    if (!d) return false;
    return d.blocking === true || String(d.severity ?? '').toLowerCase() === 'critical';
  });
}

function collectExistingReasons(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

export function evaluateDraftReviewPolicy(input: DraftReviewPolicyInput): DraftReviewPolicy {
  const reasons: string[] = [];
  const name = String(input.name ?? '');
  const upperName = name.toUpperCase();
  const qaGate = asRecord(input.qa_gate);
  const artifact = asRecord(input.diagnostic_artifact);
  const artifactQa = asRecord(artifact?.qa);

  if (upperName.includes('QA-FLAGGED')) {
    reasons.push('Draft is QA-FLAGGED and must be sent to re-edit or manually reviewed before approval.');
  }
  if (input.review_required === true || input.qa_review_required === true) {
    reasons.push('Draft metadata requires operator review before approval.');
  }
  if (qaGate?.qa_review_required === true || artifactQa?.qa_review_required === true) {
    reasons.push('QA gate requires review before approval.');
  }
  if (String(qaGate?.final_verdict ?? artifactQa?.final_verdict ?? '').toUpperCase() === 'FAIL') {
    reasons.push('QA final verdict is FAIL.');
  }
  if (hasBlockingDefect(qaGate?.defects) || hasBlockingDefect(artifactQa?.defects)) {
    reasons.push('Draft has blocking QA defects.');
  }
  for (const existing of collectExistingReasons(input.approval_blocked_reasons)) {
    reasons.push(existing);
  }

  const unique = [...new Set(reasons)];
  return {
    review_required: unique.length > 0,
    approval_blocked: unique.length > 0,
    approval_blocked_reasons: unique,
    approval_policy_version: 'qa-review-gate-v1',
  };
}
