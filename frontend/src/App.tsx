import { useCallback, useEffect, useState } from 'react';
import type { User } from 'oidc-client-ts';
import { ApiError, getEmployer, getHello } from './api/client';
import type { Employer } from './api/types';
import { Onboarding } from './components/Onboarding';
import { EmployeesPanel } from './components/EmployeesPanel';
import { EmployerPanel } from './components/EmployerPanel';
import { PayRunsPanel } from './components/PayRunsPanel';
import { TaxPanel } from './components/TaxPanel';
import { getUser, handleRedirectCallback, isAuthConfigured, isSigninRedirect, login, logout } from './auth/cognito';

type HelloState = { status: 'loading' } | { status: 'ok'; message: string } | { status: 'error'; message: string };
type AuthState = { status: 'loading' } | { status: 'signed-out' } | { status: 'signed-in'; user: User };
/** The signed-in user's employer profile lives server-side, keyed by their
 * token's `sub` claim (design-doc.md §7.1) — so it follows the login across
 * browsers/devices instead of being remembered per-browser. */
type ProfileState =
  | { status: 'loading' }
  | { status: 'missing' }
  | { status: 'ready'; employer: Employer }
  | { status: 'error'; message: string };
type Tab = 'payruns' | 'tax' | 'employees' | 'employer';

const TABS: { id: Tab; label: string }[] = [
  { id: 'payruns', label: 'Pay runs' },
  { id: 'tax', label: 'Tax' },
  { id: 'employees', label: 'Employees' },
  { id: 'employer', label: 'Employer' },
];

function App() {
  const [hello, setHello] = useState<HelloState>({ status: 'loading' });
  const [auth, setAuth] = useState<AuthState>({ status: 'loading' });
  const [profile, setProfile] = useState<ProfileState>({ status: 'loading' });
  const [tab, setTab] = useState<Tab>('payruns');

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

  const loadProfile = useCallback(async () => {
    setProfile({ status: 'loading' });
    try {
      const employer = await getEmployer();
      setProfile({ status: 'ready', employer });
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) {
        setProfile({ status: 'missing' }); // first sign-in for this account
      } else {
        setProfile({
          status: 'error',
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }, []);

  useEffect(() => {
    if (auth.status !== 'signed-in') return;
    void loadProfile();
  }, [auth.status, loadProfile]);

  return (
    <>
      <header className="app-header">
        <h1>Pappy</h1>
        {auth.status === 'signed-in' && (
          <p className="who">
            Signed in as <code>{auth.user.profile.email}</code>{' '}
            <button type="button" className="link" onClick={() => void logout()}>
              Sign out
            </button>
            {' · '}
            <span className={`api-dot ${hello.status === 'ok' ? 'ok' : hello.status === 'error' ? 'error' : ''}`}>
              {hello.status === 'ok'
                ? 'API connected'
                : hello.status === 'error'
                  ? 'API unreachable'
                  : 'Checking API…'}
            </span>
          </p>
        )}
      </header>

      {auth.status === 'loading' && <p>Loading…</p>}

      {auth.status === 'signed-out' && (
        <div className="card">
          <p>Household payroll manager.</p>
          <button
            type="button"
            disabled={!isAuthConfigured()}
            onClick={() => void login()}
            title={isAuthConfigured() ? undefined : 'Cognito not configured — see .env.example'}
          >
            Sign in
          </button>
          {!isAuthConfigured() && (
            <p className="muted">
              Set <code>VITE_COGNITO_*</code> env vars — see <code>.env.example</code>
            </p>
          )}
          {hello.status === 'error' && (
            <p className="muted">
              Backend check failed: <code>{hello.message}</code>
            </p>
          )}
        </div>
      )}

      {auth.status === 'signed-in' && profile.status === 'loading' && <p>Loading…</p>}

      {auth.status === 'signed-in' && profile.status === 'missing' && (
        <Onboarding
          onReady={(employer) => setProfile({ status: 'ready', employer })}
        />
      )}

      {auth.status === 'signed-in' && profile.status === 'error' && (
        <div className="card">
          <p className="error-banner">Could not load your profile: {profile.message}</p>
          <button type="button" onClick={() => void loadProfile()}>
            Retry
          </button>
        </div>
      )}

      {auth.status === 'signed-in' && profile.status === 'ready' && (
        <>
          <nav className="tabs" aria-label="Sections">
            {TABS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                className={tab === id ? 'tab active' : 'tab'}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </nav>

          {tab === 'payruns' && <PayRunsPanel key="payruns" />}
          {tab === 'tax' && <TaxPanel key="tax" />}
          {tab === 'employees' && <EmployeesPanel key="employees" />}
          {tab === 'employer' && (
            <EmployerPanel
              employer={profile.employer}
              onUpdated={(updated) => setProfile({ status: 'ready', employer: updated })}
            />
          )}
        </>
      )}

      <footer className="app-footer muted">
        Pay stub PDFs, reminders, and the document store arrive in later phases (design-doc.md §9).
      </footer>
    </>
  );
}

export default App;
