import { useState } from 'react';
import { login } from '../api';

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('analyst');
  const [password, setPassword] = useState('breathe2026');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="logo" style={{ marginBottom: 24 }}>
          <span className="leaf">🌿</span>
          <span>Breathe ESG</span>
        </div>
        <h1>Sign in</h1>
        <p className="subtitle">
          Multi-tenant carbon emissions platform
        </p>

        {error && <div className="login-error">{error}</div>}

        <div className="form-group">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            placeholder="Enter username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoFocus
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
          />
        </div>

        <button
          type="submit"
          className="btn btn-primary btn-full"
          disabled={loading}
        >
          {loading ? <><span className="spinner" /> Signing in...</> : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
