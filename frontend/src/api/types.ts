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
}

export interface EmployerUpdate {
  legal_name?: string;
  ein?: string;
  wa_esd_account_number?: string | null;
  ubi?: string | null;
  address?: Address;
}

export interface Employer {
  employer_id: string;
  legal_name: string;
  ein: string;
  wa_esd_account_number?: string | null;
  ubi?: string | null;
  address: Address;
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
  rate_table_version?: number | null;
  created_at: string;
  updated_at: string;
  finalized_at?: string | null;
  voided_at?: string | null;
}
