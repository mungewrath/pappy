/**
 * Cognito Hosted UI auth — placeholder.
 *
 * Per the design doc (§2.2, §7.1), auth is a Cognito user pool with Hosted UI
 * and TOTP MFA, and API Gateway validates the resulting JWT natively. There is
 * no AWS account yet, so nothing here makes a network call — this module just
 * pins down the shape the real integration will have:
 *
 *   - `AUTH_CONFIG` mirrors what Terraform's `auth` module will output
 *     (user pool ID, app client ID, Hosted UI domain) once it exists.
 *   - `login()` / `logout()` will redirect to/from the Hosted UI.
 *   - `getAccessToken()` will read the token Hosted UI redirects back with
 *     and hand it to the API client as an `Authorization: Bearer` header.
 *
 * TODO once the `auth` Terraform module is applied:
 *   1. Fill in `AUTH_CONFIG` from `terraform output`, or better, generate this
 *      file at build time from Terraform outputs / SSM Parameter Store.
 *   2. Replace the stubs below with real Hosted UI redirects and an
 *      authorization-code + PKCE token exchange (no client secret — SPA
 *      clients don't get one).
 *   3. Wire `getAccessToken()` into the generated API client's request
 *      interceptor.
 */

export interface AuthConfig {
  /** Cognito user pool ID, e.g. "us-west-2_abc123". */
  userPoolId: string;
  /** App client ID for this SPA (public client, no secret). */
  userPoolClientId: string;
  /** Hosted UI domain, e.g. "pappy-auth.auth.us-west-2.amazoncognito.com". */
  hostedUiDomain: string;
  /** Where Hosted UI redirects back to after login. */
  redirectUri: string;
  /** Where Hosted UI redirects back to after logout. */
  logoutUri: string;
}

// Placeholder values — replaced once the `auth` Terraform module exists and
// has real outputs. Left blank rather than fake-populated so a forgotten wire-up
// fails loudly instead of silently pointing at a config that looks plausible.
export const AUTH_CONFIG: AuthConfig = {
  userPoolId: '',
  userPoolClientId: '',
  hostedUiDomain: '',
  redirectUri: window.location.origin,
  logoutUri: window.location.origin,
};

export function isAuthConfigured(): boolean {
  return Boolean(
    AUTH_CONFIG.userPoolId && AUTH_CONFIG.userPoolClientId && AUTH_CONFIG.hostedUiDomain,
  );
}

/**
 * Redirects the browser to the Cognito Hosted UI login page.
 *
 * Real implementation: build the `/oauth2/authorize` URL with
 * `response_type=code`, a PKCE `code_challenge`, `client_id`, and
 * `redirect_uri`, then `window.location.assign(url)`.
 */
export function login(): void {
  if (!isAuthConfigured()) {
    throw new Error(
      'Cognito is not configured yet — set AUTH_CONFIG once the `auth` Terraform module is applied.',
    );
  }
  throw new Error('login() is a placeholder — not yet implemented.');
}

/**
 * Redirects the browser to the Cognito Hosted UI logout endpoint, clearing
 * the Hosted UI session, then returns to `logoutUri`.
 */
export function logout(): void {
  if (!isAuthConfigured()) {
    throw new Error(
      'Cognito is not configured yet — set AUTH_CONFIG once the `auth` Terraform module is applied.',
    );
  }
  throw new Error('logout() is a placeholder — not yet implemented.');
}

/**
 * Returns the current access token (JWT) to send as
 * `Authorization: Bearer <token>`, or `null` if not signed in.
 *
 * Real implementation: read the token set from the Hosted UI redirect
 * (authorization-code + PKCE exchange), cached in memory, and refreshed
 * using the refresh token before it expires.
 */
export function getAccessToken(): string | null {
  return null;
}
