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

export interface PayRunCreate {
  period_start: string;
  period_end: string;
  pay_date: string;
  hour_lines?: HourLine[];
}

/** Gross pay with the overtime premium broken out (design-doc.md §5.4). */
export interface GrossPayResult {
  regular_hours: DecimalString;
  overtime_hours: DecimalString;
  other_paid_hours: DecimalString;
  unpaid_hours: DecimalString;
  hourly_rate: DecimalString;
  straight_time_pay: DecimalString;
  overtime_premium_pay: DecimalString;
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
