/**
 * API client for the Pappy backend (FastAPI; see backend/pappy/api).
 *
 * The base URL comes from `VITE_API_BASE_URL` (see `.env.example`), which
 * will be the API Gateway HTTP API invoke URL once deployed. Locally it
 * points at `uvicorn` running the FastAPI app directly (see backend/README).
 *
 * Every request carries the Cognito access token (`../auth/cognito.ts`) —
 * the deployed API's JWT authorizer rejects anything without one, and the
 * backend scopes all data to the token's `sub` claim (design-doc.md §7.1):
 * no employer ID is ever sent by the client.
 *
 * Decimal/money fields are strings in both directions (design-doc.md §5.5,
 * see `./types.ts`).
 */

import { getAccessToken } from '../auth/cognito';
import type {
  Address,
  BackfillCreate,
  BackfillResult,
  Document,
  DocumentDownload,
  EarningsSummary,
  Employee,
  EmployeeCreate,
  EmployeeUpdate,
  Employer,
  EmployerCreate,
  EmployerUpdate,
  FinalizePendingResult,
  PayRun,
  PayRunCreate,
  PayRunDraftUpdate,
  QuarterlyEstimates,
  Reminder,
  ScheduleHWorksheet,
  TestSendRequest,
  TestSendResponse,
  W4Election,
  W2Summary,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export interface HelloResponse {
  message: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Pulls FastAPI's `{detail: ...}` shape out of an error response when present. */
async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = (await response.json())?.detail;
  } catch {
    // Non-JSON body; fall through to the generic message.
  }
  const message =
    typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => JSON.stringify(item)).join('; ')
        : `${response.status} ${response.statusText}`;
  return new ApiError(response.status, message);
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
}

async function request<T>(path: string, { method = 'GET', body }: RequestOptions = {}): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Health -----------------------------------------------------------------

export function getHello(): Promise<HelloResponse> {
  return request<HelloResponse>('/hello');
}

// --- Employer ---------------------------------------------------------------

export function createEmployer(data: EmployerCreate): Promise<Employer> {
  return request<Employer>('/employers', { method: 'POST', body: data });
}

export function getEmployer(): Promise<Employer> {
  return request<Employer>('/employers');
}

export function updateEmployer(patch: EmployerUpdate): Promise<Employer> {
  return request<Employer>('/employers', { method: 'PATCH', body: patch });
}

// --- Employees --------------------------------------------------------------

const employeePath = (employeeId?: string): string =>
  `/employees${employeeId ? `/${encodeURIComponent(employeeId)}` : ''}`;

export function listEmployees(): Promise<Employee[]> {
  return request<Employee[]>(employeePath());
}

export function createEmployee(data: EmployeeCreate): Promise<Employee> {
  return request<Employee>(employeePath(), { method: 'POST', body: data });
}

export function updateEmployee(employeeId: string, patch: EmployeeUpdate): Promise<Employee> {
  return request<Employee>(employeePath(employeeId), {
    method: 'PATCH',
    body: patch,
  });
}

export function deleteEmployee(employeeId: string): Promise<void> {
  return request<void>(employeePath(employeeId), { method: 'DELETE' });
}

// --- W-4 elections (design-doc.md §5.3) --------------------------------------

const w4Path = (employeeId: string): string =>
  `/employees/${encodeURIComponent(employeeId)}/w4`;

/** Records an effective-dated W-4 election. A pay run resolves the election in
 * effect on its pay date, so a mid-year re-election never rewrites history. */
export function addW4Election(employeeId: string, data: W4Election): Promise<W4Election> {
  return request<W4Election>(w4Path(employeeId), {
    method: 'POST',
    body: data,
  });
}

export function listW4Elections(employeeId: string): Promise<W4Election[]> {
  return request<W4Election[]>(w4Path(employeeId));
}

// --- Pay runs ---------------------------------------------------------------

const payRunPath = (runId?: string, suffix?: string): string =>
  `/payruns${runId ? `/${encodeURIComponent(runId)}` : ''}${suffix ?? ''}`;

export function listPayRuns(year?: number): Promise<PayRun[]> {
  const query = year === undefined ? '' : `?year=${year}`;
  return request<PayRun[]>(`${payRunPath()}${query}`);
}

/** Opens a new draft; omitting `hour_lines` auto-seeds from the employee's
 * default schedule (design-doc.md §6.1). */
export function createPayRunDraft(
  employeeId: string,
  data: PayRunCreate,
): Promise<PayRun> {
  return request<PayRun>(
    `${payRunPath()}/employees/${encodeURIComponent(employeeId)}`,
    { method: 'POST', body: data },
  );
}

export function getPayRun(runId: string): Promise<PayRun> {
  return request<PayRun>(payRunPath(runId));
}

/** Replaces a DRAFT run's hour lines and extra pay lines; gross is recomputed
 * server-side. Both lists are always sent — a replace that omitted either would
 * silently drop the other. */
export function updatePayRunDraft(
  runId: string,
  data: PayRunDraftUpdate,
): Promise<PayRun> {
  return request<PayRun>(payRunPath(runId), { method: 'PUT', body: data });
}

export function finalizePayRun(runId: string): Promise<PayRun> {
  return request<PayRun>(payRunPath(runId, '/finalize'), {
    method: 'POST',
    body: {},
  });
}

/** Creates weekly DRAFT runs across a historical date range (Phase 6).
 * Overlapping weeks are skipped, never overwritten. */
export function backfillHistory(
  employeeId: string,
  data: BackfillCreate,
): Promise<BackfillResult> {
  return request<BackfillResult>(
    `${payRunPath()}/employees/${encodeURIComponent(employeeId)}/backfill`,
    { method: 'POST', body: data },
  );
}

// --- Reminders (design-doc.md §6.6) ------------------------------------------

const reminderPath = (reminderId?: string, suffix?: string): string =>
  `/reminders${reminderId ? `/${encodeURIComponent(reminderId)}` : ''}${suffix ?? ''}`;

/** Open reminders by default; `open_only: false` includes acknowledged history. */
export function listReminders(openOnly = true): Promise<Reminder[]> {
  return request<Reminder[]>(`${reminderPath()}?open_only=${openOnly}`);
}

export function acknowledgeReminder(reminderId: string): Promise<Reminder> {
  return request<Reminder>(reminderPath(reminderId, '/acknowledge'), {
    method: 'POST',
    body: {},
  });
}

/** Finalizes pending drafts oldest-pay-date-first. Stops at the first
 * failure so wage-base caps stay correct; the rest stay pending. */
export function finalizePendingRuns(params?: { year?: number }): Promise<FinalizePendingResult> {
  const query = params?.year === undefined ? '' : `?year=${params.year}`;
  return request<FinalizePendingResult>(`${payRunPath()}/finalize-pending${query}`, {
    method: 'POST',
    body: {},
  });
}

// --- Tax-year artifacts (design-doc.md §6.4–§6.6) -----------------------------

const taxYearPath = (taxYear: number, suffix?: string): string =>
  `/tax-years/${taxYear}${suffix ?? ''}`;

export function getQuarterlyEstimates(taxYear: number): Promise<QuarterlyEstimates> {
  return request<QuarterlyEstimates>(taxYearPath(taxYear, '/1040-es'));
}

export function getScheduleH(taxYear: number): Promise<ScheduleHWorksheet> {
  return request<ScheduleHWorksheet>(taxYearPath(taxYear, '/schedule-h'));
}

export function getW2Summaries(taxYear: number): Promise<W2Summary[]> {
  return request<W2Summary[]>(taxYearPath(taxYear, '/w2'));
}

export function getEarningsSummaries(taxYear: number): Promise<EarningsSummary[]> {
  return request<EarningsSummary[]>(taxYearPath(taxYear, '/earnings-summary'));
}

/** Fires a reminder rule right now — the same code path as the scheduled
 * Lambda, including idempotency per due date. */
export function testSendReminder(data: TestSendRequest): Promise<TestSendResponse> {
  return request<TestSendResponse>(reminderPath(undefined, '/test-send'), {
    method: 'POST',
    body: data,
  });
}

/** Downloads the SSA EFW2 upload file. SSNs are sent transiently for this
 * one generation — the backend never stores or logs them (§7.3). */
export async function downloadEfw2(
  taxYear: number,
  employeeSsns: Record<string, string>,
): Promise<void> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_BASE_URL}${taxYearPath(taxYear, '/efw2')}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ employee_ssns: employeeSsns }),
  });
  if (!response.ok) throw await toApiError(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `EFW2-${taxYear}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

// --- Documents (Phase 3; design-doc.md §3.1, §6.2) ----------------------------

/** Generate a pay stub PDF for a finalized pay run (idempotent). */
export function generatePayStub(runId: string): Promise<Document> {
  return request<Document>(payRunPath(runId, '/pay-stub'), {
    method: 'POST',
    body: {},
  });
}

export function listDocuments(taxYear?: number): Promise<Document[]> {
  const query = taxYear === undefined ? '' : `?tax_year=${taxYear}`;
  return request<Document[]>(`/documents${query}`);
}

/** Get a short-lived URL for downloading a generated document. */
export function downloadDocumentUrl(docId: string): Promise<DocumentDownload> {
  return request<DocumentDownload>(`/documents/${encodeURIComponent(docId)}/download`);
}

// --- Form helpers -----------------------------------------------------------

export function emptyAddress(): Address {
  return { line1: '', line2: null, city: '', state: '', zip_code: '' };
}
