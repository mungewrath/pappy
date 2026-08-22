import { useEffect, useState } from 'react';
import type { User } from 'oidc-client-ts';
import { getHello } from './api/client';
import { clearStoredEmployerId, loadStoredEmployerId } from './api/employerStorage';
import { Onboarding } from './components/Onboarding';
import { EmployeesPanel } from './components/EmployeesPanel';
import { EmployerPanel } from './components/EmployerPanel';
import { PayRunsPanel } from './components/PayRunsPanel';
import { getUser, handleRedirectCallback, isAuthConfigured, isSigninRedirect, login, logout } from './auth/cognito';

type HelloState = { status: 'loading' } | { status: 'ok'; message: string } | { status: 'error'; message: string };
type AuthState = { status: 'loading' } | { status: 'signed-out' } | { status: 'signed-in'; user: User };
type Tab = 'payruns' | 'employees' | 'employer';

const TABS: { id: Tab; label: string }[] = [
  { id: 'payruns', label: 'Pay runs' },
  { id: 'employees', label: 'Employees' },
  { id: 'employer', label: 'Employer' },
];

function App() {
  const [hello, setHello] = useState<HelloState>({ status: 'loading' });
  const [auth, setAuth] = useState<AuthState>({ status: 'loading' });
  const [employerId, setEmployerId] = useState<string | null>(loadStoredEmployerId());
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

      {auth.status === 'signed-in' && !employerId && (
        <Onboarding onReady={setEmployerId} />
      )}

      {auth.status === 'signed-in' && employerId && (
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

          {tab === 'payruns' && <PayRunsPanel key="payruns" employerId={employerId} />}
          {tab === 'employees' && <EmployeesPanel key="employees" employerId={employerId} />}
          {tab === 'employer' && (
            <EmployerPanel
              onSwitch={() => {
                clearStoredEmployerId();
                setEmployerId(null);
              }}
            />
          )}
        </>
      )}

      <footer className="app-footer muted">
        Pay stubs, withholding, and year-end artifacts arrive in later phases (design-doc.md §9).
      </footer>
    </>
  );
}

export default App;
