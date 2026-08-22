/**
 * Where the SPA remembers which single employer profile it manages.
 *
 * The API currently takes `employer_id` as a path parameter; once the API
 * derives it from the JWT `sub` claim (design-doc.md §7.1) this can go away.
 */

const EMPLOYER_ID_KEY = 'pappy.employerId';

export function loadStoredEmployerId(): string | null {
  return window.localStorage.getItem(EMPLOYER_ID_KEY);
}

export function storeEmployerId(id: string): void {
  window.localStorage.setItem(EMPLOYER_ID_KEY, id);
}

export function clearStoredEmployerId(): void {
  window.localStorage.removeItem(EMPLOYER_ID_KEY);
}
