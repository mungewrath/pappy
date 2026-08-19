import { useEffect, useState } from 'react';
import { getHello } from './api/client';
import { isAuthConfigured, login } from './auth/cognito';
import './index.css';

type HelloState = { status: 'loading' } | { status: 'ok'; message: string } | { status: 'error'; message: string };

function App() {
  const [hello, setHello] = useState<HelloState>({ status: 'loading' });

  useEffect(() => {
    getHello()
      .then((res) => setHello({ status: 'ok', message: res.message }))
      .catch((err: unknown) =>
        setHello({ status: 'error', message: err instanceof Error ? err.message : String(err) }),
      );
  }, []);

  return (
    <>
      <h1>Pappy</h1>
      <p>
        Household payroll manager — SPA shell calling <code>GET /hello</code>.
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

      <p style={{ marginTop: '1.5rem' }}>
        <button
          type="button"
          disabled={!isAuthConfigured()}
          onClick={login}
          title={isAuthConfigured() ? undefined : 'Cognito not configured yet — see src/auth/cognito.ts'}
        >
          Sign in
        </button>
        {!isAuthConfigured() && (
          <>
            <br />
            <small>Cognito Hosted UI is a placeholder — see src/auth/cognito.ts</small>
          </>
        )}
      </p>
    </>
  );
}

export default App;
