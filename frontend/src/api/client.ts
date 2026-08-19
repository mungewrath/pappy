/**
 * Minimal API client for the hello-world backend.
 *
 * The base URL comes from `VITE_API_BASE_URL` (see `.env.example`), which
 * will be the API Gateway HTTP API invoke URL once deployed. Locally it
 * points at `uvicorn` running the FastAPI app directly (see backend/README).
 *
 * Once Cognito is wired up (see `../auth/cognito.ts`), this is where the
 * `Authorization: Bearer <token>` header gets attached to every request.
 */

import { getAccessToken } from '../auth/cognito';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export interface HelloResponse {
  message: string;
}

async function apiFetch<T>(path: string): Promise<T> {
  const token = getAccessToken();
  const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

  const response = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!response.ok) {
    throw new Error(`${path} responded with ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getHello(): Promise<HelloResponse> {
  return apiFetch<HelloResponse>('/hello');
}
