/**
 * Cognito Hosted UI auth (§2.2, §7.1).
 *
 * Auth is a Cognito user pool with Hosted UI and TOTP MFA; API Gateway's JWT
 * authorizer validates the resulting access token natively — the API never
 * sees a request that isn't already authenticated. This module wraps
 * `oidc-client-ts`'s `UserManager` to run the OAuth2 authorization-code +
 * PKCE flow against Hosted UI (no client secret — SPA clients don't get
 * one) and exposes the access token to the API client.
 *
 * Config comes from `VITE_COGNITO_*` env vars, populated from the `auth`
 * Terraform module's outputs (see `.env.example` / frontend/README.md).
 */

import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';

export interface AuthConfig {
  /** Cognito user pool ID, e.g. "us-west-2_abc123". */
  userPoolId: string;
  /** App client ID for this SPA (public client, no secret). */
  userPoolClientId: string;
  /** Hosted UI domain, e.g. "pappy-auth.auth.us-west-2.amazoncognito.com". */
  hostedUiDomain: string;
  /** AWS region the user pool lives in, e.g. "us-west-2". */
  region: string;
  /** Where Hosted UI redirects back to after login. */
  redirectUri: string;
  /** Where Hosted UI redirects back to after logout. */
  logoutUri: string;
}

export const AUTH_CONFIG: AuthConfig = {
  userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID ?? '',
  userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID ?? '',
  hostedUiDomain: import.meta.env.VITE_COGNITO_DOMAIN ?? '',
  region: import.meta.env.VITE_COGNITO_REGION ?? 'us-west-2',
  redirectUri: window.location.origin,
  logoutUri: window.location.origin,
};

export function isAuthConfigured(): boolean {
  return Boolean(
    AUTH_CONFIG.userPoolId && AUTH_CONFIG.userPoolClientId && AUTH_CONFIG.hostedUiDomain,
  );
}

let userManager: UserManager | null = null;

function getUserManager(): UserManager {
  if (!isAuthConfigured()) {
    throw new Error(
      'Cognito is not configured — set VITE_COGNITO_* env vars (see .env.example).',
    );
  }

  if (!userManager) {
    userManager = new UserManager({
      // Cognito's user pool issuer, discoverable at
      // https://cognito-idp.<region>.amazonaws.com/<userPoolId>/.well-known/openid-configuration
      authority: `https://cognito-idp.${AUTH_CONFIG.region}.amazonaws.com/${AUTH_CONFIG.userPoolId}`,
      client_id: AUTH_CONFIG.userPoolClientId,
      redirect_uri: AUTH_CONFIG.redirectUri,
      response_type: 'code',
      scope: 'openid email profile',
      userStore: new WebStorageStateStore({ store: window.localStorage }),
      // Renews using the refresh token (30-day validity, see the `auth`
      // Terraform module) rather than a silent iframe — simpler, and
      // Cognito's Hosted UI doesn't play well with iframe-based silent
      // renew behind CloudFront/S3.
      automaticSilentRenew: true,
      loadUserInfo: true,
    });
  }

  return userManager;
}

/** Redirects the browser to the Cognito Hosted UI login page. */
export function login(): Promise<void> {
  return getUserManager().signinRedirect();
}

/**
 * Redirects the browser to the Cognito Hosted UI logout endpoint, clearing
 * the Hosted UI session, then returns to `logoutUri`.
 *
 * Cognito's logout endpoint doesn't implement standard OIDC end-session, so
 * this navigates there directly rather than using `signoutRedirect()`.
 */
export async function logout(): Promise<void> {
  const manager = getUserManager();
  await manager.removeUser();

  const params = new URLSearchParams({
    client_id: AUTH_CONFIG.userPoolClientId,
    logout_uri: AUTH_CONFIG.logoutUri,
  });
  window.location.assign(`https://${AUTH_CONFIG.hostedUiDomain}/logout?${params.toString()}`);
}

/**
 * Completes the authorization-code exchange after Hosted UI redirects back
 * with `?code=...&state=...`. Call this once on app load when those query
 * params are present.
 */
export function handleRedirectCallback(): Promise<User> {
  return getUserManager().signinRedirectCallback();
}

export function isSigninRedirect(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.has('code') && params.has('state');
}

/** Returns the signed-in user (from local storage), or `null`. */
export function getUser(): Promise<User | null> {
  if (!isAuthConfigured()) return Promise.resolve(null);
  return getUserManager().getUser();
}

/**
 * Returns the current access token (JWT) to send as
 * `Authorization: Bearer <token>`, or `null` if not signed in.
 */
export async function getAccessToken(): Promise<string | null> {
  const user = await getUser();
  if (!user || user.expired) return null;
  return user.access_token;
}
