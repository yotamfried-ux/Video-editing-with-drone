# Cross-layer logical-consistency test basis

Date: 2026-07-17

This document defines the external engineering basis for SportReel's cross-layer
pipeline tests. The tests are intentionally not isolated token checks. They exercise
architecture boundaries and prove that one run keeps the same business truth from
analysis through operator approval.

## Official sources

### AWS — test architecture boundaries and contracts

AWS Prescriptive Guidance, **Testing serverless applications on AWS**:

- https://docs.aws.amazon.com/prescriptive-guidance/latest/serverless-application-testing/introduction.html

The guide treats subsystem boundaries as test seams, recommends contract validation
at those boundaries, and recommends capturing events flowing through asynchronous
systems. SportReel applies this to analyzer → selector → renderer → QA → manifest →
storage → operator API.

AWS Prescriptive Guidance, **Resilience analysis framework**:

- https://docs.aws.amazon.com/prescriptive-guidance/latest/resilience-analysis-framework/introduction.html

SportReel uses repeatable failure-mode scenarios rather than assuming that green unit
tests imply a resilient workflow.

### Google Cloud — observe technical and business outcomes

Google Cloud Well-Architected Framework, **Detect potential failures by using
observability**:

- https://cloud.google.com/architecture/framework/reliability/slo-and-alerts

The guidance distinguishes technical telemetry from application-specific business
metrics. SportReel therefore verifies both process success and product outcomes such
as eligible-athlete coverage, usable-wave preservation, final QA, and operator
publishability.

### Microsoft Azure — correlation and idempotency across the full request path

Azure Architecture Center, **Microservices assessment and readiness**:

- https://learn.microsoft.com/en-us/azure/architecture/guide/technology-choices/microservices-assessment

The guidance recommends one correlation ID across the service chain and idempotency
keys for safe retries. SportReel uses a run identity and immutable draft identity to
join pipeline, manifest, storage, re-edit, and approval state.

Azure Architecture Center, **Retry pattern**:

- https://learn.microsoft.com/en-us/azure/architecture/patterns/retry

The guidance requires distinguishing transient failures and considering idempotency.
Status propagation and upload reconciliation must therefore be retryable without
creating duplicate drafts or contradictory terminal states.

### GitHub — failures must produce failing workflow results

GitHub Actions, **Setting exit codes for actions**:

- https://docs.github.com/actions/creating-actions/setting-exit-codes-for-actions

A non-zero exit code represents failure. Product-critical installation, evidence,
business-gate, and status-propagation failures must not be swallowed behind a green
workflow.

GitHub Actions, **Workflow syntax**:

- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

Dependent validation must require successful predecessor jobs and must not use
`continue-on-error` for product invariants.

## SportReel cross-layer invariants

The integrated harness must prove all of the following in one invocation:

1. The production entrypoint and every manual entrypoint install one canonical,
   fail-fast runtime stack in one deterministic order.
2. A focused sub-window never manufactures identity evidence. New positive evidence
   must be evaluated on the focused window.
3. Every detected action-performing athlete remains in the accountability denominator,
   even when every event is rejected.
4. The partition budget includes every segment that will appear in the rendered
   timeline; late additions cannot push a Part over 90 seconds.
5. Rendered-timeline evidence includes every visual occurrence, including any teaser.
6. QA repair maps defects to immutable event IDs and actual rendered offsets.
7. One immutable media-spec snapshot is used for a manifest revision.
8. Selection, rendering, QA, upload, and publishability remain distinct states.
9. REVIEW listing and approval use authoritative server-side publishability evidence,
   not client flags or filenames.
10. GitHub, durable run status, and operator status converge on one read-back verified
    terminal state, or a durable retry/outbox record remains.

A production experiment is allowed only after this harness and the existing suite are
green on the exact merge candidate.