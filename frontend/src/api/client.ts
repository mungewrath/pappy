/**
 * API client for the Pappy backend (FastAPI; see backend/pappy/api).
 *
 * The base URL comes from `VITE_API_BASE_URL` (see `.env.example`), which
 * will be the API Gateway HTTP API invoke URL once deployed. Locally it
 * points at `uvicorn` running the FastAPI app directly (see backend/README).
 *
 * Every request carries the Cognito access token (`../auth/cognito.ts`) —
 * the deployed API's JWT authorizer rejects anything without one.
 *
 * Decimal/money fields are strings in both directions (design-doc.md §5.5,
 * see `./types.ts`).
 */

import { getAccessToken } from '../auth/cognito';
import type {
  Address,
  Employee,
  EmployeeCreate,
  EmployeeUpdate,
  Employer,
  EmployerCreate,
  EmployerUpdate,
  HourLine,
  PayRun,
  PayRunCreate,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export interface HelloResponse {
  message: string;
}

class ApiError extends Error {
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

export function getEmployer(employerId: string): Promise<Employer> {
  return request<Employer>(`/employers/${encodeURIComponent(employerId)}`);
}

export function updateEmployer(
  employerId: string,
  patch: EmployerUpdate,
): Promise<Employer> {
  return request<Employer>(`/employers/${encodeURIComponent(employerId)}`, {
    method: 'PATCH',
    body: patch,
  });
}

// --- Employees --------------------------------------------------------------

const employeePath = (employerId: string, employeeId?: string): string =>
  `/employers/${encodeURIComponent(employerId)}/employees${
    employeeId ? `/${encodeURIComponent(employeeId)}` : ''
  }`;

export function listEmployees(employerId: string): Promise<Employee[]> {
  return request<Employee[]>(employeePath(employerId));
}

export function createEmployee(
  employerId: string,
  data: EmployeeCreate,
): Promise<Employee> {
  return request<Employee>(employeePath(employerId), { method: 'POST', body: data });
}

export function updateEmployee(
  employerId: string,
  employeeId: string,
  patch: EmployeeUpdate,
): Promise<Employee> {
  return request<Employee>(employeePath(employerId, employeeId), {
    method: 'PATCH',
    body: patch,
  });
}

export function deleteEmployee(employerId: string, employeeId: string): Promise<void> {
  return request<void>(employeePath(employerId, employeeId), { method: 'DELETE' });
}

// --- Pay runs ---------------------------------------------------------------

const payRunBase = (employerId: string): string =>
  `/employers/${encodeURIComponent(employerId)}/payruns`;

export function listPayRuns(employerId: string, year?: number): Promise<PayRun[]> {
  const query = year === undefined ? '' : `?year=${year}`;
  return request<PayRun[]>(`${payRunBase(employerId)}${query}`);
}

/** Opens a new draft; omitting `hour_lines` auto-seeds from the employee's
 * default schedule (design-doc.md §6.1). */
export function createPayRunDraft(
  employerId: string,
  employeeId: string,
  data: PayRunCreate,
): Promise<PayRun> {
  return request<PayRun>(
    `${payRunBase(employerId)}/employees/${encodeURIComponent(employeeId)}`,
    { method: 'POST', body: data },
  );
}

export function getPayRun(employerId: string, runId: string): Promise<PayRun> {
  return request<PayRun>(
    `${payRunBase(employerId)}/${encodeURIComponent(runId)}`,
  );
}

/** Replaces a DRAFT run's hour lines; gross is recomputed server-side. */
export function updatePayRunHours(
  employerId: string,
  runId: string,
  hourLines: HourLine[],
): Promise<PayRun> {
  return request<PayRun>(
    `${payRunBase(employerId)}/${encodeURIComponent(runId)}/hours`,
    { method: 'PUT', body: { hour_lines: hourLines } },
  );
}

export function finalizePayRun(
  employerId: string,
  runId: string,
): Promise<PayRun> {
  return request<PayRun>(
    `${payRunBase(employerId)}/${encodeURIComponent(runId)}/finalize`,
    { method: 'POST', body: {} },
  );
}

// --- Form helpers -----------------------------------------------------------

export function emptyAddress(): Address {
  return { line1: '', line2: null, city: '', state: '', zip_code: '' };
}
