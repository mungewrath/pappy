import { useEffect, useState } from 'react';
import type { User } from 'oidc-client-ts';
import { getHello } from './api/client';
import { getUser, handleRedirectCallback, isAuthConfigured, isSigninRedirect, login, logout } from './auth/cognito';
import './index.css';

type HelloState = { status: 'loading' } | { status: 'ok'; message: string } | { status: 'error'; message: string };
type AuthState = { status: 'loading' } | { status: 'signed-out' } | { status: 'signed-in'; user: User };

function App() {
  const [hello, setHello] = useState<HelloState>({ status: 'loading' });
  const [auth, setAuth] = useState<AuthState>({ status: 'loading' });

  useEffect(() => {
    if (!isAuthConfigured()) {
      setAuth({ status: 'signed-out' });
      return;
    }

    (async () => {
      if (isSigninRedirect()) {
        const user = await handleRedirectCallback();
        // Drop ?code&state from the URL so a refresh doesn't replay the callback.
        window.history.replaceState({}, document.title, window.location.pathname);
        setAuth({ status: 'signed-in', user });
        return;
      }

      const user = await getUser();
      setAuth(user && !user.expired ? { status: 'signed-in', user } : { status: 'signed-out' });
    })();
  }, []);

  useEffect(() => {
    if (auth.status !== 'signed-in') return;

    getHello()
      .then((res) => setHello({ status: 'ok', message: res.message }))
      .catch((err: unknown) =>
        setHello({ status: 'error', message: err instanceof Error ? err.message : String(err) }),
      );
  }, [auth.status]);

  return (
    <>
      <h1>Pappy</h1>
      <p>Household payroll manager.</p>

      {auth.status === 'loading' && <p>Loading…</p>}

      {auth.status === 'signed-out' && (
        <p>
          <button
            type="button"
            disabled={!isAuthConfigured()}
            onClick={() => void login()}
            title={isAuthConfigured() ? undefined : 'Cognito not configured — see .env.example'}
          >
            Sign in
          </button>
          {!isAuthConfigured() && (
            <>
              <br />
              <small>Set VITE_COGNITO_* env vars — see .env.example</small>
            </>
          )}
        </p>
      )}

      {auth.status === 'signed-in' && (
        <>
          <p>
            Signed in as <code>{auth.user.profile.email}</code>{' '}
            <button type="button" onClick={() => void logout()}>
              Sign out
            </button>
          </p>

          <p>
            SPA shell calling <code>GET /hello</code>.
          </p>

          <div className={`status ${hello.status === 'error' ? 'error' : 'ok'}`}>
            {hello.status === 'loading' && 'Calling backend…'}
            {hello.status === 'ok' && hello.message}
            {hello.status === 'error' && (
              <>
                Could not reach the API: <code>{hello.message}</code>
                <br />
                Is the backend running? See <code>backend/README.md</code>.
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}

export default App;
