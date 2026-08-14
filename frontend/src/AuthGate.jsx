import { useEffect, useState } from 'react';
import { supabase } from './supabaseClient';
import App from './App';
import { applyTheme, getInitialTheme } from './theme';

export default function AuthGate() {
  const [session, setSession] = useState(undefined); // undefined = still checking
  const [mode, setMode] = useState('signin'); // 'signin' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [theme, setTheme] = useState(getInitialTheme());

  useEffect(() => { applyTheme(theme); }, [theme]);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    const fn = mode === 'signin'
      ? supabase.auth.signInWithPassword({ email, password })
      : supabase.auth.signUp({ email, password });
    const { data, error: authError } = await fn;
    setBusy(false);
    if (authError) {
      setError(authError.message);
      return;
    }
    if (mode === 'signup' && !data.session) {
      setNotice('Check your email to confirm your account, then sign in.');
      setMode('signin');
    }
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
  }

  if (session === undefined) {
    return null; // avoid a login-form flash while the session check resolves
  }

  if (session) {
    return <App accessToken={session.access_token} userEmail={session.user?.email} onSignOut={handleSignOut} />;
  }

  return (
    <div className="auth-wrap">
      <header className="masthead" style={{ border: 'none', paddingBottom: 0, marginBottom: 8, position: 'static' }}>
        <div className="masthead-left">
          <div className="masthead-logo">GT</div>
          <h1>Gap<span>·</span>Telemetry</h1>
        </div>
        <button className="theme-toggle" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
          {theme === 'dark' ? '☀ Light' : '● Dark'}
        </button>
      </header>
      <section className="panel">
        <h2>{mode === 'signin' ? 'Sign in' : 'Create an account'}</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="full">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" required autoComplete="email"
                     value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="full">
              <label htmlFor="password">Password</label>
              <input id="password" type="password" required minLength={6}
                     autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                     value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <div className="full">
              <button className="primary" type="submit" disabled={busy} style={{ width: '100%' }}>
                {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Sign up'}
              </button>
            </div>
          </div>
        </form>
        {error && <div className="error">{error}</div>}
        {notice && <div className="error" style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>{notice}</div>}
        <div className="auth-toggle">
          {mode === 'signin' ? (
            <>No account yet? <button className="link" onClick={() => setMode('signup')}>Create one</button></>
          ) : (
            <>Already have an account? <button className="link" onClick={() => setMode('signin')}>Sign in</button></>
          )}
        </div>
      </section>
    </div>
  );
}
