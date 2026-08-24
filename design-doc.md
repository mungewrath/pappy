# Pappy — Design Document

Status: **Draft for review**
Scope: proposed implementation for the requirements in [requirements-doc.md](requirements-doc.md)

> **Not tax advice.** Every rate, wage base, and filing threshold in this document is
> treated as *configuration data*, not as code, and every value cited below is
> illustrative and must be verified against current IRS/WA ESD publications before
> a filing season is trusted. See [Tax rate tables](#52-tax-rate-tables).

---

## 1. Summary

Pappy is a single-household payroll manager for one W-2 household employee (a nanny)
in Washington State. It tracks a weekly pay cycle, computes withholding, produces
pay stubs, retains an immutable history for tax and FSA purposes, generates the
year-end and quarterly artifacts a household employer owes, and reminds the employer
when something is due.

The design targets one primary user (the employer), one employee record, and roughly
52 pay runs per year. That is a deliberately tiny workload — the architecture is
chosen to cost approximately nothing at idle, not to scale.

### Design principles

1. **Immutable ledger, mutable drafts.** A pay run is editable until it is *finalized*;
   after that it is append-only and corrections happen via explicit adjustment entries.
   Tax artifacts derive from finalized runs only.
2. **Rates are data, not code.** Tax years change annually. A new tax year is a new
   row in a rate table plus a test fixture, never a code change.
3. **Compute once, store the result.** Each finalized pay run stores the full
   computation *and* the ID of the rate table version used. Regenerating a 2027 W-2
   in 2031 must not depend on 2031 rate logic.
4. **Zero idle cost.** No provisioned capacity, no NAT gateway, no always-on container.
5. **Documents are generated, never hand-assembled.** Pay stubs, FSA receipts,
   Schedule H, and W-2 all render from the same ledger.

---

## 2. Architecture

### 2.1 Overview

```
                    ┌──────────────────────────────┐
   Browser ────────▶│ CloudFront + S3 (SPA bundle) │
  (mobile/desktop)  └──────────────────────────────┘
        │
        │  OIDC login
        ▼
   ┌─────────────────┐
   │ Cognito         │  Hosted UI, single user pool
   │ User Pool       │
   └─────────────────┘
        │ JWT
        ▼
   ┌──────────────────────┐      ┌───────────────────┐
   │ API Gateway HTTP API │─────▶│ Lambda (API)      │
   │ + JWT authorizer     │      │ single function   │
   └──────────────────────┘      └─────────┬─────────┘
                                           │
                     ┌─────────────────────┼────────────────────┐
                     ▼                     ▼                    ▼
             ┌──────────────┐      ┌──────────────┐     ┌──────────────┐
             │ DynamoDB     │      │ S3 documents │     │ SES / SNS    │
             │ (on-demand)  │      │ (versioned)  │     │ (reminders)  │
             └──────────────┘      └──────────────┘     └──────────────┘
                     ▲
                     │
        ┌────────────┴──────────────┐
        │ EventBridge Scheduler     │──▶ Lambda (scheduler) ──▶ pay-run draft
        │ weekly / quarterly / EOY  │                            + reminder email
        └───────────────────────────┘
```

### 2.2 Component choices and rationale

| Concern | Choice | Why |
|---|---|---|
| Frontend | React + Vite SPA, S3 + CloudFront (OAC), responsive layout | Static hosting is pennies; one responsive codebase satisfies "mobile or desktop" without a native app |
| Auth | Cognito user pool, Hosted UI, no MFA | Free tier covers a single user indefinitely; offloads password/reset handling. API Gateway validates the JWT natively — no custom auth code. MFA was dropped for sign-in convenience (§7.1); revisit if the threat model changes |
| API | API Gateway **HTTP API** (not REST API) + one Lambda | HTTP API is ~70% cheaper and supports JWT authorizers natively. A single "monolith Lambda" keeps cold starts and deployment simple at this scale |
| Runtime | Python 3.13, ARM64, 512 MB | `decimal.Decimal` in the standard library is the right primitive for money — exact base-10 arithmetic with explicit, auditable rounding contexts (§5.5). Also the team's preferred language. ARM64 is cheaper per GB-s |
| API framework | FastAPI + Pydantic v2, adapted via Mangum | Pydantic validates request bodies and rate-table JSON against the same models, and emits an OpenAPI schema the SPA's client is generated from — recovering the type-sharing that a single-language stack would have given for free |
| Data | DynamoDB, on-demand, PITR enabled | On-demand has no idle cost. Access patterns are known and narrow (see §4) |
| Documents | S3 bucket, versioning + object lock in governance mode | Generated PDFs must be retained ~4 years for IRS; object lock prevents accidental deletion |
| PDF generation | `pypdf` filling official IRS AcroForm PDFs; `reportlab` for stubs/receipts/earnings summaries | Filling the government's own form PDF avoids re-implementing layout that changes yearly. Both are pure-Python, so no native build step in the Lambda package |
| Scheduling | EventBridge Scheduler | Cron without a running host; one schedule per reminder class |
| Email | SES (verified sender + verified recipient identity) | Cheap; sandbox mode is sufficient since recipients are fixed and few |
| IaC | Terraform | The infrastructure here is a fixed, declarative set of ~30 resources with no dynamic construction — Terraform's plan/state model fits that better than CDK's synthesize-then-diff, `terraform plan` is a readable review artifact, and it is the more standard choice for anyone who inherits this. No CDK bootstrap stack, and no requirement that IaC share the app's language |
| Secrets/config | SSM Parameter Store (standard tier) | Free; Secrets Manager charges per secret per month |
| Observability | CloudWatch Logs, 30-day retention, one billing alarm | Log retention is the main sneaky cost — cap it |

### 2.3 Cost model

Everything above is on-demand. At roughly 52 pay runs, a few hundred API calls a
month, and a few dozen generated PDFs a year, the expected steady-state bill is
**dominated by fixed non-serverless items**:

- Route 53 hosted zone: ~$0.50/mo (only if a custom domain is used — optional)
- Everything else: within perpetual free tier or fractions of a cent

Cognito, Lambda, DynamoDB on-demand, S3, SES, and EventBridge Scheduler all have
zero minimum. **Explicitly avoided:** RDS/Aurora (even Serverless v2 has a minimum
ACU), NAT Gateway, ALB, ECS/Fargate, provisioned concurrency, Aurora DSQL, OpenSearch.
Lambdas run outside a VPC, so no NAT is needed.

A CloudWatch billing alarm at $5/mo is part of the stack — a runaway loop should
page the owner, not surprise them at month end.

### 2.4 Repository layout and deployment

```
pappy/
├── terraform/
│   ├── main.tf, providers.tf, variables.tf, outputs.tf
│   ├── backend.tf              # S3 state + native S3 lockfile (no DynamoDB lock table)
│   └── modules/
│       ├── api/               # HTTP API, JWT authorizer, Lambda, IAM
│       ├── auth/              # Cognito user pool, client, hosted UI domain
│       ├── data/              # DynamoDB table, KMS keys, S3 document bucket
│       ├── frontend/          # SPA bucket, CloudFront + OAC, cert
│       └── scheduling/        # EventBridge schedules, scheduler Lambda, SES identity
├── backend/
│   ├── pappy/
│   │   ├── money.py           # Decimal-backed Money (§5.5)
│   │   ├── calc/              # pure calculation engine — no AWS imports
│   │   ├── models/            # Pydantic domain models
│   │   ├── repo/              # DynamoDB access, single-table keys
│   │   ├── documents/         # pypdf / reportlab generators
│   │   └── api/               # FastAPI app + Mangum handler
│   ├── tests/                 # pytest, hypothesis, moto
│   └── pyproject.toml         # uv-managed
├── rates/2026.json ...        # versioned statutory tables (§5.2)
└── frontend/                  # React + Vite SPA, generated API client
```

**Packaging.** Lambda artifacts are built outside Terraform — `uv` exports pinned
requirements, dependencies are installed for `linux/aarch64`, and the zip is uploaded
to an artifacts bucket. Terraform consumes the object key/version as a variable rather
than building anything itself, keeping `terraform plan` free of build side effects and
its diffs meaningful. Pure-Python dependencies (`pypdf`, `reportlab`, `pydantic`)
avoid any cross-compilation step.

**State.** S3 backend with native S3 state locking and versioning enabled. Two
workspaces, `dev` and `prod`, differing only in variable values.

**CI.** On PR: `ruff`, `mypy --strict`, `pytest`, `terraform validate`, and
`terraform plan` posted to the PR. On merge to `main`: build artifacts,
`terraform apply` to `dev`, then `prod` behind a manual approval.

---

## 3. Domain model

### 3.1 Entities

**Employer** — one per deployment. EIN, WA ESD account number, UBI, address,
filing preferences, FSA plan details.

**Employee** — nanny. Name, SSN (encrypted, see §7.3), address, hire date, pay rate,
overtime rate policy, default weekly schedule.

**W4Election** — effective-dated child of Employee, so a mid-year re-election never
rewrites earlier finalized runs. Holds filing status, Step 2c checkbox, dependent
credit, other income, deductions, and extra per-period withholding, plus the date it
takes effect. See §5.3.

**RateTable** — versioned, keyed by tax year. All statutory numbers live here:
Social Security rate + wage base, Medicare rate + additional-Medicare threshold,
FUTA rate + wage base + state credit, WA PFML employee/employer split and rate,
WA Cares rate, WA UI rate (employer-specific, assigned annually by ESD), federal
withholding percentage-method tables (Pub. 15-T), household-employer coverage
thresholds.

**PayRun** — one per pay period. States: `DRAFT` → `FINALIZED` → (`VOIDED`).
Holds period start/end, pay date, hour lines, computed gross, each withholding
line, net pay, employer tax accruals, and `rateTableVersion`.

**HourLine** — date, hours, category (`REGULAR`, `OVERTIME`, `PTO`, `HOLIDAY`,
`SICK`, `UNPAID`). Auto-seeded from the default schedule, then editable.

**Adjustment** — post-finalization correction, or a non-hours item: bonus, mileage
reimbursement (non-taxable, tracked separately), advance repayment.

**Document** — generated artifact. Type (`PAY_STUB`, `FSA_RECEIPT`, `SCHEDULE_H`,
`W2`, `W3`, `FORM_1040ES`, `EARNINGS_SUMMARY`), tax year, S3 key, SHA-256, generated-at, and the set of
PayRun IDs it covers.

**ReminderRule / ReminderInstance** — what is due, when, whether it was sent,
whether it was acknowledged.

### 3.2 Pay run lifecycle

```
   EventBridge (Fri 06:00 local)
            │
            ▼
   ┌──────────────────┐   employer edits hours   ┌──────────────────┐
   │ DRAFT created    │◀────────────────────────▶│ recompute on     │
   │ from default     │                          │ every change     │
   │ schedule         │                          └──────────────────┘
   └────────┬─────────┘
            │ employer reviews stub preview, confirms
            ▼
   ┌──────────────────┐
   │ FINALIZED        │  immutable; stub PDF written to S3;
   │ + rateTableVer   │  YTD accumulators advanced
   └────────┬─────────┘
            │ mistake found later
            ▼
   ┌──────────────────┐
   │ ADJUSTMENT entry │  never edits the original; carries its own
   │ on a later run   │  computation and reason
   └──────────────────┘
```

Rationale: tax artifacts are produced months after the fact. If a finalized run
could be silently edited, an already-issued FSA receipt or W-2 would quietly stop
matching the ledger. Adjustments keep the audit trail honest.

---

## 4. Data model (DynamoDB)

Single table, `pappy`, on-demand, PITR on.

| Entity | PK | SK |
|---|---|---|
| Employer | `EMPLOYER#<id>` | `PROFILE` |
| Employee | `EMPLOYER#<id>` | `EMPLOYEE#<empId>` |
| W-4 election | `EMPLOYER#<id>` | `EMPLOYEE#<empId>#W4#<effectiveDate>` |
| PayRun | `EMPLOYER#<id>` | `PAYRUN#<payDate>#<runId>` |
| Adjustment | `EMPLOYER#<id>` | `PAYRUN#<payDate>#<runId>#ADJ#<adjId>` |
| YTD accumulator | `EMPLOYER#<id>` | `YTD#<taxYear>#<empId>` |
| Document | `EMPLOYER#<id>` | `DOC#<taxYear>#<type>#<docId>` |
| Reminder | `EMPLOYER#<id>` | `REMINDER#<dueDate>#<ruleId>` |
| RateTable | `RATES#<taxYear>` | `VERSION#<n>` |

Sort keys are date-prefixed and zero-padded ISO, so "all pay runs in 2026",
"all documents for tax year 2026", and "reminders due before X" are all
single `Query` calls with a `begins_with` or range condition. No GSI is needed
at this scale. Item collection size for a decade of weekly runs is well under
the 10 GB partition limit.

**YTD accumulators** are maintained transactionally: finalizing a pay run writes
the `PAYRUN` item and updates the `YTD` item in one `TransactWriteItems` with a
condition that the run is still `DRAFT`. This is what makes wage-base caps
(Social Security, FUTA, WA UI) correct without re-reading the whole year — though
the year *can* be recomputed from scratch as a consistency check (see §8).

---

## 5. Payroll calculation

### 5.1 Computation order

For each pay run, given hour lines and the employee's elections:

1. **Gross** = Σ(hours × applicable rate). Overtime at 1.5× for hours over 40 in a
   workweek — note that the FLSA domestic-service exemption from overtime applies
   only to live-in employees, and Washington has its own rules; the policy is
   configurable per employee with a default of "overtime applies."
2. **Employee withholding**
   - Social Security: `rate × min(gross, remaining wage base)`
   - Medicare: `rate × gross`, plus Additional Medicare above the threshold
   - Federal income tax: percentage method from the Pub. 15-T table in the rate
     table, using W-4 elections. **Enabled** — a household employer withholds FIT
     only by mutual agreement with the employee, and that agreement is assumed here,
     so FIT withholding is on by default and the employee's W-4 is required input
     (see §5.3).
   - WA Paid Family & Medical Leave: employee share
   - WA Cares Fund: employee share (with exemption flag support)
   - Washington has **no state income tax** — that line is absent by design
3. **Net pay** = gross − withholding − any post-tax deductions
4. **Employer accruals** (not withheld, but tracked — these drive Schedule H and
   quarterly estimates): employer Social Security, employer Medicare, FUTA
   (0.6% effective on the first $7,000 when the state credit applies), WA UI at
   the employer's assigned rate, WA PFML employer share
5. **Rounding**: per-line half-up rounding at the cent, matching the IRS
   convention. See §5.5 for the money representation.

### 5.2 Tax rate tables

Rate tables are JSON, checked into the repo under `rates/<year>.json`, parsed into
Pydantic models with `Decimal` fields (so a malformed rate fails at load, not at
payroll time), loaded into DynamoDB by a deploy-time seeder, and **immutable once a pay run
references them**. Correcting a table mid-year creates version `n+1`; already
finalized runs keep pointing at version `n`.

Each year's file ships with a golden-test fixture: a set of (gross, elections) →
expected-withholding cases derived from the IRS publication's own worked examples.
CI fails if the computation drifts.

An **annual rollover checklist** is generated as a January reminder: new SS wage
base, new Pub. 15-T tables, new FUTA credit reduction status for WA, new ESD rate
notice, new WA Cares/PFML rates, new household-employer coverage threshold.

### 5.3 Federal income tax withholding

FIT withholding is a first-class part of the engine rather than an optional path.
That has consequences worth stating up front:

- **W-4 is required input.** The employee record stores the full set of W-4 Step 1–4
  elections: filing status, multiple-jobs checkbox (Step 2c), dependent credit amount
  (Step 3), other income (4a), deductions (4b), and extra per-period withholding (4c).
  A missing or invalid W-4 blocks finalization rather than silently defaulting.
- **Percentage method, annualized.** The engine annualizes the pay-period wage using
  52 periods, applies the Pub. 15-T percentage-method table for the filing status and
  Step 2c state, subtracts the Step 3 credit on an annualized basis, then divides back
  down to the period and adds Step 4c. Two table sets are needed per year: the
  standard tables and the "Step 2c checked" tables.
- **Table shape.** Pub. 15-T tables are bracket lists — `{ threshold, baseTax,
  marginalRate }` per filing status per table set. They live in the same versioned
  per-year JSON as the other statutory values (§5.2) and are covered by golden
  fixtures drawn from the publication's own worked examples.
- **Floor at zero.** Computed FIT is never negative; the Step 3 credit reduces
  withholding to zero and no further. No refundable behavior in payroll.
- **Deposit obligation.** Withheld FIT is the employer's to remit. It flows into the
  quarterly 1040-ES figure alongside the Social Security and Medicare accruals, and
  onto Schedule H's federal-income-tax-withheld line (§6.4). Turning withholding on
  is what makes the quarterly reminder load-bearing rather than informational — the
  money is already out of the employee's check and owed to the IRS.
- **Mid-year W-4 changes** are effective-dated on the employee record. A pay run
  resolves the W-4 version in effect on its pay date, so a re-elected W-4 in July
  does not retroactively change June's finalized runs.

### 5.4 Pay stub

Rendered per finalized run: period, pay date, hours by category, rate, gross,
each withholding line with current and YTD columns, net, and employer info.
Washington requires an itemized statement each pay period; the YTD columns also
make the FSA receipt trivially defensible.

**Overtime premium breakdown.** Overtime is shown as two explicit lines rather than
one blended figure — straight-time hours at the base rate, and the 0.5× premium on
overtime hours as its own line — with the effective overtime rate and the workweek
the overtime was earned in. This is the "overtime premium" artifact from the
requirements: not a separate document, but a required section of the stub, and the
same breakdown appears in the year view and CSV export so an overtime question can
be answered from the archive without recomputing.

### 5.5 Money representation

`Decimal` is the reason Python was chosen for the backend, so the money path is
defined explicitly rather than left to convention:

- **A `Money` value object wraps a `Decimal`**, quantized to `0.01` with
  `ROUND_HALF_UP`. It refuses construction from `float` — only `str`, `int`, or
  `Decimal` — which makes the "someone passed a float in" bug impossible rather than
  merely discouraged.
- **Rates stay unquantized.** Tax rates and hour counts are `Decimal` at full
  precision; only monetary *results* are quantized, and only once per line. Quantizing
  intermediates is how withholding drifts by pennies over a year.
- **One explicit `decimal` context** is set at module import (`ROUND_HALF_UP`,
  ample precision, traps on `InvalidOperation` and `DivisionByZero`) so a bad
  computation raises instead of silently producing `NaN`.
- **DynamoDB stores money as a decimal string**, not `N` and not a float. `boto3`'s
  serializer round-trips `Decimal` natively; storing the string keeps the stored value
  byte-identical to what was computed and displayed.
- **JSON serialization** goes through a Pydantic serializer that emits money as a
  string, so the SPA never sees an IEEE-754 approximation of a paycheck. The frontend
  formats strings for display and does no arithmetic on money.
- **Mypy in strict mode** on the calculation package; `float` is banned from its
  public signatures by a lint rule.

---

## 6. Features

### 6.1 Auto-populated hours

The employee record carries a default weekly schedule (e.g. Mon–Fri, 9 hours).
Each Friday morning, the scheduler Lambda creates a `DRAFT` run pre-filled from
that schedule. The employer opens it, adjusts the exceptions (a sick day, a late
night), and finalizes. The common week is zero-edit; the unusual week is a few taps.

### 6.2 Audit & historical view

A year view lists every finalized run with gross/withholding/net and YTD running
totals, filterable by date range, exportable as CSV. Every document ever generated
is listed with its hash and the runs it covers, so a regenerated document can be
proven identical to the one originally issued.

### 6.3 FSA receipts

A Dependent Care FSA reimbursement requires: provider name, provider address,
provider TIN/SSN, dates of service, amount paid, and the dependent's name. The
generator takes a date range, sums the *gross wages* for runs in that range
(employer taxes paid are also generally eligible — configurable), and emits a PDF
receipt with a statement of services and a signature block. Because the DCFSA
limit is annual and per-household, the app tracks cumulative claimed amounts
against a configured plan limit and warns before over-claiming.

### 6.4 Schedule H

Generated for a tax year from finalized runs:
- Total cash wages subject to Social Security and Medicare
- Employee + employer Social Security and Medicare
- Federal income tax withheld, if any
- FUTA: wages subject, state contributions paid, credit computation
- Any WA credit-reduction handling if applicable that year

Output is a filled official Schedule H (Form 1040) PDF plus a worksheet showing
which pay runs contributed to each line — the worksheet is the part that makes an
audit survivable.

### 6.5 W-2 / W-3

W-2 Copies B, C, and 2 are generated for the employee. **Copy A is not printed
from this app** — it must be filed with the SSA. The design assumes filing through
SSA's *Business Services Online* (free), and the app produces both the filled
employee copies and an SSA `EFW2` fixed-width file for BSO upload. W-3 is only
required for paper filing; filing electronically through BSO generates it
automatically. (See open questions, §10.)

### 6.6 Reminders

| Rule | Cadence | Action |
|---|---|---|
| Weekly pay | Friday 06:00 America/Los_Angeles | Create draft run + email "review and pay" |
| Quarterly estimated tax | Due dates ± lead time | Email with computed 1040-ES amount from YTD accruals |
| WA ESD quarterly report | End of month after quarter close | Email with the wage figures to enter in EAMS |
| W-2 to employee | Mid-January | Generate the year-end packet — W-2 Copies B/C/2 plus an annual earnings summary carrying the overtime premium breakdown (§5.4) — email checklist, deadline Jan 31 |
| Annual rate rollover | Early January | Checklist of statutory values to verify (§5.2) |
| Schedule H | Tax filing season | Generate and email link |
| IRS guidance links | Each January | Curated links to Pub. 926, Pub. 15-T, Schedule H instructions, WA ESD household-employer page — presented as a "confirm nothing changed" checklist |

EventBridge Scheduler fires the scheduler Lambda; the Lambda materializes
`ReminderInstance` rows and sends via SES. Reminders are **acknowledgeable** —
an unacknowledged reminder stays visible on the dashboard and re-nags, so a missed
quarterly payment doesn't disappear into an inbox.

The IRS-guidance reminder is deliberately a *link* to authoritative pages rather
than a claim about current rules. The app should never be the last word on a
statutory question.

### 6.7 User experience

Single responsive SPA. The mobile-primary flow is the weekly one: open the
notification → see the pre-filled week → adjust → confirm → stub PDF. Desktop
gets the denser views: year table, document archive, form generation, settings.
No offline support in v1; a household payroll app can require connectivity.

---

## 7. Security

### 7.1 Authentication & authorization

Cognito user pool with a strong password policy and no self-signup (users are
created by the administrator). MFA is intentionally off — traded away for sign-in
convenience given the single-user threat model; revisit if the user base grows
beyond the household employer and an accountant/employee `VIEWER`. API Gateway's
JWT authorizer rejects unauthenticated requests before Lambda is invoked. The
Lambda additionally derives `employerId` from the token's `sub` claim and scopes
every DynamoDB key by it — the client never supplies `employerId`. Two roles:
`OWNER` (full access) and `VIEWER` (read-only; useful for an accountant, and for
the employee to see their own stubs in a later version).

### 7.2 Transport & storage

HTTPS only, HSTS, CloudFront with OAC so the S3 bucket is never public. All buckets
and tables encrypted at rest; DynamoDB with a customer-managed KMS key.

### 7.3 PII handling

SSN and bank details are the sensitive fields. They are stored encrypted with a
dedicated KMS key via client-side envelope encryption, decrypted only inside the
document-generation path, never returned to the browser in full (masked as
`***-**-1234` everywhere in the UI), and never written to logs. A structured
logger with an explicit allowlist of loggable fields enforces this — redaction by
default rather than by remembering.

Document S3 objects are served via short-lived pre-signed URLs, never public reads.

### 7.4 Blast radius

Least-privilege IAM: the API Lambda can read/write only the `pappy` table and its
own S3 prefix; the scheduler Lambda additionally holds `ses:SendEmail` for a single
verified identity. No wildcard resource ARNs.

---

## 8. Correctness strategy

Payroll is a domain where a silent arithmetic error surfaces a year later as an
IRS notice. Testing is weighted accordingly.

- **Golden fixtures**: worked examples from IRS publications, per tax year, as
  described in §5.2. These are the primary regression net.
- **Property tests**: net + withholding ≡ gross for every run; YTD accumulators
  always equal the sum of finalized runs; wage-base caps never exceeded; no
  negative net without an explicit adjustment.
- **Recompute-and-diff job**: a monthly Lambda that recomputes the entire tax year
  from finalized runs and compares against stored accumulators, emailing on any
  discrepancy. This catches transaction bugs that unit tests can't.
- **Snapshot tests on generated PDFs**: field-level assertions on the filled
  AcroForm values, not pixel diffs.
- **Test stack**: `pytest`, with `hypothesis` for the property tests above and
  `moto` to fake DynamoDB/S3/SES in unit tests. `mypy --strict` and `ruff` in CI.
- **Local dev**: FastAPI runs directly under `uvicorn` against DynamoDB Local — the
  Mangum adapter is only engaged in Lambda, so the whole app runs offline with no
  emulator and no `terraform apply`.

---

## 9. Implementation plan

| Phase | Deliverable | Notes |
|---|---|---|
| 0 | Terraform root module + remote state, CI, single-table DynamoDB, Cognito, hello-world FastAPI Lambda, SPA shell with login | Prove the zero-cost, authenticated path end to end |
| 1 | Domain model, `Money`/`Decimal` primitives, calculation engine incl. Pub. 15-T FIT, current-year rate table + golden tests | Pure Python package, no AWS — highest-value, testable in isolation |
| 2 | Pay run CRUD, default schedule seeding, finalize transaction, YTD accumulators | The core loop |
| 3 | Pay stub PDF + document store | First artifact out the door |
| 4 | Reminders: EventBridge + SES + acknowledgement | Weekly loop becomes hands-off |
| 5 | Year view, CSV export, FSA receipts | Audit + reimbursement |
| 6 | Schedule H, W-2 copies, annual earnings summary, EFW2 file, quarterly 1040-ES figures | Tax season |
| 7 | Recompute-and-diff job, billing alarm, backup/restore runbook | Operational hardening |

Phase 1 is deliberately first and deliberately AWS-free: if the arithmetic is
wrong, nothing else matters, and it is by far the easiest part to get right in a
pure test harness.

---

## 10. Open questions

Answers to the requirements doc's open questions, plus what the design surfaced.
These are **assessments to verify**, not legal conclusions.

**W-3** — Likely not needed. W-3 is a transmittal for *paper* W-2 Copy A filings.
Filing electronically through SSA Business Services Online generates the equivalent
automatically. The design assumes electronic filing and therefore treats W-3 as an
optional generator (§6.5). *Decision needed: confirm BSO electronic filing is the
intended path.*

**WA ESD EAMS Authorization Request Form** — Needed once, at setup, not per filing.
It authorizes an account to file quarterly reports in EAMS. This is a one-time
onboarding task, so the design treats it as a **setup checklist item with a link**
rather than a generated form.

**Form 2848 (Power of Attorney)** — Not needed if the employer files their own
returns. It is only required to authorize a third party (an accountant) to
represent the employer before the IRS. Out of scope unless a `VIEWER`-role
accountant is expected to file on the employer's behalf.

**Form SS-4 (EIN application)** — Needed once, before the first payroll, and only
if the employer doesn't already have an EIN. Best done through the IRS online EIN
assistant, which issues the number immediately. Treated as a **setup checklist
item**, not a generator.

**Additional use cases the requirements didn't cover** — surfaced while designing:

1. **Quarterly WA ESD wage reporting.** Washington household employers generally
   report quarterly to ESD for UI, PFML, and WA Cares. This is a recurring
   obligation distinct from the federal quarterly estimate and is included in §6.6.
2. **Form W-4 and I-9 collection at hire.** I-9 must be completed and retained; it
   is not filed anywhere. Worth a document-retention slot.
3. **New-hire reporting to the state**, generally required shortly after hire.
4. **Washington's paid sick leave accrual.** Employees accrue paid sick leave at a
   statutory minimum rate; the design's `SICK` hour category and accrual tracking
   anticipate this, but the accrual rules need confirmation.
5. **Mileage / expense reimbursement** — non-taxable, must not inflate gross wages.
   Modeled as a distinct `Adjustment` type.
6. **Termination / final paycheck**, and issuing a W-2 mid-year if employment ends.
7. **Employee self-service** — letting the nanny view their own stubs and W-2 is a
   natural v2, and the `VIEWER` role leaves room for it.
8. **Backup and account recovery.** With one user and no MFA, account recovery
   is via verified email — a lost/compromised email locks the employer out of
   their own tax records (or worse, a compromised email is now the entire
   auth boundary). A documented recovery path (e.g. an exported encrypted
   archive) is required, not optional; reconsider MFA if this risk proves
   unacceptable in practice.
9. **Multi-year rate maintenance is the real ongoing cost of this app.** Every
    January someone must update the rate tables. The rollover checklist (§5.2)
    makes that explicit rather than leaving it as tribal knowledge.

MU: of these, 4 (sick leave) and 5 (mileage) seem like good value-adds

---

## 11. Explicitly out of scope for v1

Direct deposit / ACH origination (the employer pays by their existing method),
multiple employees, multiple states, time clock / GPS punch-in, employee mobile app,
integration with tax-prep software, and anything resembling a general-purpose
payroll product.
