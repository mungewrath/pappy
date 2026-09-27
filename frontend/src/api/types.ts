/**
 * TypeScript mirrors of the backend's Pydantic models (backend/pappy/models).
 *
 * Per design-doc.md §5.5, the API serializes money and other decimals as
 * strings ("1234.56") so the SPA never sees an IEEE-754 approximation of a
 * paycheck. This module keeps that story intact on the client side: decimal
 * values stay strings end-to-end, and `format.ts` formats them for display.
 * The frontend does no arithmetic on money.
 */

/** A decimal serialized by the backend as an exact string. */
export type DecimalString = string;

export interface Address {
  line1: string;
  line2?: string | null;
  city: string;
  state: string;
  zip_code: string;
}

export type HourCategory =
  | 'REGULAR'
  | 'OVERTIME'
  | 'PTO'
  | 'HOLIDAY'
  | 'SICK'
  | 'UNPAID';

export const HOUR_CATEGORIES: readonly HourCategory[] = [
  'REGULAR',
  'OVERTIME',
  'PTO',
  'HOLIDAY',
  'SICK',
  'UNPAID',
];

export type OvertimePolicy = 'APPLIES' | 'EXEMPT';

export const OVERTIME_POLICIES: readonly OvertimePolicy[] = ['APPLIES', 'EXEMPT'];

export type PayRunStatus = 'DRAFT' | 'FINALIZED' | 'VOIDED';

// --- Employer --------------------------------------------------------------

export interface EmployerCreate {
  legal_name: string;
  ein: string;
  wa_esd_account_number?: string | null;
  ubi?: string | null;
  address: Address;
  /** ESD-assigned experience rate (e.g. "0.0128"), from the annual rate notice. */
  wa_ui_experience_rate?: DecimalString | null;
}

export interface EmployerUpdate {
  legal_name?: string;
  ein?: string;
  wa_esd_account_number?: string | null;
  ubi?: string | null;
  address?: Address;
  wa_ui_experience_rate?: DecimalString | null;
}

export interface Employer {
  employer_id: string;
  legal_name: string;
  ein: string;
  wa_esd_account_number?: string | null;
  ubi?: string | null;
  address: Address;
  wa_ui_experience_rate?: DecimalString | null;
  created_at: string;
  updated_at: string;
}

// --- Employee ---------------------------------------------------------------

/** One line of the default weekly schedule; `weekday` is 0=Monday..6=Sunday. */
export interface DefaultScheduleLine {
  weekday: number;
  hours: DecimalString;
}

export interface EmployeeCreate {
  full_name: string;
  address: Address;
  hire_date: string;
  hourly_rate: DecimalString;
  overtime_policy?: OvertimePolicy;
  default_schedule?: DefaultScheduleLine[];
}

export interface EmployeeUpdate {
  full_name?: string;
  address?: Address;
  hire_date?: string;
  hourly_rate?: DecimalString;
  overtime_policy?: OvertimePolicy;
  default_schedule?: DefaultScheduleLine[];
  termination_date?: string | null;
}

export interface Employee {
  employer_id: string;
  employee_id: string;
  full_name: string;
  address: Address;
  hire_date: string;
  termination_date?: string | null;
  hourly_rate: DecimalString;
  overtime_policy: OvertimePolicy;
  default_schedule: DefaultScheduleLine[];
  created_at: string;
  updated_at: string;
}

// --- W-4 elections (design-doc.md §3.1, §5.3) --------------------------------

export type FilingStatus = 'SINGLE_OR_MFS' | 'MARRIED_JOINTLY' | 'HEAD_OF_HOUSEHOLD';

export const FILING_STATUSES: readonly FilingStatus[] = [
  'SINGLE_OR_MFS',
  'MARRIED_JOINTLY',
  'HEAD_OF_HOUSEHOLD',
];

export const FILING_STATUS_LABELS: Readonly<Record<FilingStatus, string>> = {
  SINGLE_OR_MFS: 'Single or married filing separately',
  MARRIED_JOINTLY: 'Married filing jointly',
  HEAD_OF_HOUSEHOLD: 'Head of household',
};

/** One effective-dated Form W-4 election. Amounts are annual except
 * `extra_withholding`, which is per pay period (Form W-4 Step 4c). */
export interface W4Election {
  effective_date: string;
  filing_status: FilingStatus;
  multiple_jobs_step2c: boolean;
  dependent_credit_amount: DecimalString;
  other_income: DecimalString;
  deductions: DecimalString;
  extra_withholding: DecimalString;
}

// --- Payroll result (computed at finalization; design-doc.md §5.1) -----------

/** The slice of the run's gross each wage-base-capped tax applied to. */
export interface TaxableWages {
  social_security: DecimalString;
  medicare: DecimalString;
  additional_medicare: DecimalString;
  futa: DecimalString;
  wa_ui: DecimalString;
  wa_pfml: DecimalString;
}

export interface EmployeeWithholding {
  social_security: DecimalString;
  medicare: DecimalString;
  additional_medicare: DecimalString;
  federal_income_tax: DecimalString;
  wa_pfml_employee: DecimalString;
  wa_cares_employee: DecimalString;
  /** Server-computed sum — the client never adds money itself (§5.5). */
  total: DecimalString;
}

export interface EmployerAccruals {
  social_security: DecimalString;
  medicare: DecimalString;
  futa: DecimalString;
  wa_ui: DecimalString;
  wa_pfml_employer: DecimalString;
  total: DecimalString;
}

export interface PayrollResult {
  gross: DecimalString;
  taxable: TaxableWages;
  withholding: EmployeeWithholding;
  net_pay: DecimalString;
  employer_accruals: EmployerAccruals;
}

// --- PayRun -----------------------------------------------------------------

export interface HourLine {
  line_id: string;
  /** ISO date, e.g. "2026-08-21". */
  work_date: string;
  hours: DecimalString;
  category: HourCategory;
}

/** A flat amount of extra pay on a run — a bonus, gift, or similar. Entered
 * directly rather than derived from hours, and taxable like any other wage
 * (design-doc.md §5.4). */
export interface ExtraPayLine {
  line_id: string;
  note: string;
  amount: DecimalString;
}

export interface PayRunCreate {
  period_start: string;
  period_end: string;
  pay_date: string;
  hour_lines?: HourLine[];
  extra_pay_lines?: ExtraPayLine[];
}

/** The whole DRAFT-editable surface of a run, sent as one replace (PUT). */
export interface PayRunDraftUpdate {
  hour_lines: HourLine[];
  extra_pay_lines: ExtraPayLine[];
}

/** Gross pay with the overtime premium and any extra pay broken out
 * (design-doc.md §5.4). */
export interface GrossPayResult {
  regular_hours: DecimalString;
  overtime_hours: DecimalString;
  other_paid_hours: DecimalString;
  unpaid_hours: DecimalString;
  hourly_rate: DecimalString;
  straight_time_pay: DecimalString;
  overtime_premium_pay: DecimalString;
  /** Sum of the run's extra pay lines; "0.00" when there are none. */
  extra_pay: DecimalString;
  gross: DecimalString;
}

export interface PayRun {
  employer_id: string;
  employee_id: string;
  run_id: string;
  status: PayRunStatus;
  period_start: string;
  period_end: string;
  pay_date: string;
  hour_lines: HourLine[];
  extra_pay_lines: ExtraPayLine[];
  gross: GrossPayResult;
  /** Present only on FINALIZED runs — the complete computation stored at
   * finalization (design-doc.md §3.1, "compute once, store the result"). */
  payroll?: PayrollResult | null;
  rate_table_version?: number | null;
  created_at: string;
  updated_at: string;
  finalized_at?: string | null;
  voided_at?: string | null;
}

// --- Document (design-doc.md §3.1) -------------------------------------------

export type DocumentType =
  | 'PAY_STUB'
  | 'FSA_RECEIPT'
  | 'SCHEDULE_H'
  | 'W2'
  | 'W3'
  | 'FORM_1040ES'
  | 'EARNINGS_SUMMARY';

export interface Document {
  employer_id: string;
  doc_id: string;
  document_type: DocumentType;
  tax_year: number;
  s3_key: string;
  sha256: string;
  filename: string;
  pay_run_ids: string[];
  /** Pay date of the run this document covers, for artifacts that span a
   * single run (a pay stub). Absent on year-wide documents (W-2, Schedule H,
   * earnings summary) and on stubs generated before the field existed. */
  pay_date?: string | null;
  created_at: string;
}

export interface DocumentDownload {
  url: string;
  sha256: string;
  filename: string;
  /** Lifetime of `url` when it is a pre-signed S3 URL; not meaningful for
   * `via: 'api'`. */
  expires_in: number;
  /** `url` may be opened directly; `api` must be fetched with the caller's
   * `Authorization` header, since a browser cannot add one to a navigation. */
  via: 'url' | 'api';
}

// --- Tax-year artifacts (Phase 6; design-doc.md §6.4–§6.6) -------------------

/** One quarter's 1040-ES contribution: withheld FIT plus both halves of
 * FICA (Schedule H lines B/D/G/I), with FUTA on top. */
export interface QuarterEstimate {
  quarter: number;
  period_start: string;
  period_end: string;
  due_date: string;
  pay_run_count: number;
  gross: DecimalString;
  federal_income_tax_withheld: DecimalString;
  social_security: DecimalString;
  medicare: DecimalString;
  additional_medicare: DecimalString;
  household_employment_taxes: DecimalString;
  futa: DecimalString;
  total: DecimalString;
  ytd_total: DecimalString;
}

export interface QuarterlyEstimates {
  tax_year: number;
  quarters: QuarterEstimate[];
  grand_total: DecimalString;
}

/** One finalized run's contribution to a year artifact (§6.4 worksheet). */
export interface ContributingRun {
  run_id: string;
  employee_id: string;
  employee_name?: string | null;
  pay_date: string;
  gross: DecimalString;
  social_security: DecimalString;
  medicare: DecimalString;
  additional_medicare: DecimalString;
  federal_income_tax_withheld: DecimalString;
  futa: DecimalString;
}

export interface ScheduleHWorksheet {
  tax_year: number;
  employer_name: string;
  employer_ein: string;
  line_a_ss_wages: DecimalString;
  line_b_ss_tax: DecimalString;
  line_c_medicare_wages: DecimalString;
  line_d_medicare_tax: DecimalString;
  line_e_subtotal: DecimalString;
  line_f_addl_medicare_wages: DecimalString;
  line_g_addl_medicare_tax: DecimalString;
  line_h_household_fica_taxes: DecimalString;
  line_i_fit_withheld: DecimalString;
  line_j_total_household_employment_taxes: DecimalString;
  line_l_futa_tax: DecimalString;
  line_m_total: DecimalString;
  contributing_runs: ContributingRun[];
}

export interface W2Box14Item {
  label: string;
  amount: DecimalString;
}

export interface W2Summary {
  tax_year: number;
  employer_name: string;
  employer_ein: string;
  employee_id: string;
  employee_name: string;
  box1_wages: DecimalString;
  box2_fit_withheld: DecimalString;
  box3_ss_wages: DecimalString;
  box4_ss_tax_withheld: DecimalString;
  box5_medicare_wages: DecimalString;
  box6_medicare_tax_withheld: DecimalString;
  box14_items: W2Box14Item[];
}

/** How much of one wage-base cap the year has consumed (§4 accumulators). */
export interface WageBaseUsage {
  name: string;
  label: string;
  wages_used: DecimalString;
  wage_base?: DecimalString | null;
  remaining?: DecimalString | null;
}

export interface QuarterGross {
  quarter: number;
  gross: DecimalString;
  ytd_gross: DecimalString;
}

export interface EarningsSummary {
  tax_year: number;
  employee_id: string;
  employee_name: string;
  hourly_rate: DecimalString;
  finalized_run_count: number;
  hours_regular: DecimalString;
  hours_overtime: DecimalString;
  hours_other_paid: DecimalString;
  hours_unpaid: DecimalString;
  straight_time_pay: DecimalString;
  overtime_premium_pay: DecimalString;
  extra_pay: DecimalString;
  gross: DecimalString;
  withholding: EmployeeWithholding;
  net_pay: DecimalString;
  employer_accruals: EmployerAccruals;
  quarterly_gross: QuarterGross[];
  wage_bases: WageBaseUsage[];
}

// --- Historical entry (Phase 6) ----------------------------------------------

export type BackfillMode = 'SCHEDULE' | 'FLAT';

export interface BackfillCreate {
  period_start: string;
  period_end: string;
  /** 0=Monday .. 6=Sunday; default 4 (Friday). */
  pay_weekday?: number;
  mode?: BackfillMode;
  /** Required for FLAT mode — spread evenly across scheduled workdays. */
  weekly_hours?: DecimalString;
}

export interface SkippedWeek {
  period_start: string;
  period_end: string;
  reason: string;
}

export interface BackfillResult {
  created: PayRun[];
  skipped: SkippedWeek[];
}

export interface FinalizeFailure {
  run_id: string;
  pay_date: string;
  detail: string;
}

export interface FinalizePendingResult {
  finalized: string[];
  failed: FinalizeFailure[];
}

// --- Reminder (design-doc.md §6.6) -------------------------------------------

export type ReminderRule =
  | 'WEEKLY_PAY'
  | 'QUARTERLY_TAX'
  | 'WA_ESD_QUARTERLY'
  | 'W2_EMPLOYEE'
  | 'ANNUAL_ROLLOVER'
  | 'SCHEDULE_H'
  | 'IRS_GUIDANCE';

export const REMINDER_RULES: readonly ReminderRule[] = [
  'WEEKLY_PAY',
  'QUARTERLY_TAX',
  'WA_ESD_QUARTERLY',
  'W2_EMPLOYEE',
  'ANNUAL_ROLLOVER',
  'SCHEDULE_H',
  'IRS_GUIDANCE',
];

export const REMINDER_RULE_LABELS: Record<ReminderRule, string> = {
  WEEKLY_PAY: 'Weekly pay review',
  QUARTERLY_TAX: 'Quarterly estimated tax',
  WA_ESD_QUARTERLY: 'WA ESD quarterly report',
  W2_EMPLOYEE: 'W-2 to employee',
  ANNUAL_ROLLOVER: 'Annual rate rollover',
  SCHEDULE_H: 'Schedule H',
  IRS_GUIDANCE: 'IRS guidance check',
};

export type ReminderStatus = 'PENDING' | 'SENT' | 'ACKNOWLEDGED';

/** One occurrence of a rule, keyed by due date server-side; the composite
 * id (`<dueDate>:<rule>`) is URL-safe and all the client needs. */
export interface Reminder {
  employer_id: string;
  rule: ReminderRule;
  due_date: string;
  status: ReminderStatus;
  subject: string;
  body: string;
  ses_message_id?: string | null;
  created_at: string;
  updated_at: string;
  sent_at?: string | null;
  acknowledged_at?: string | null;
}

export interface TestSendRequest {
  rule: ReminderRule;
  fire_date?: string | null;
  due_date?: string | null;
  create_drafts?: boolean;
  send_email?: boolean;
}

export interface TestSendResponse {
  created: Reminder[];
  email_transport: 'ses' | 'log';
}
