import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isLoggedIn, logout } from './api';
import LoginPage from './components/LoginPage';
import IngestPage from './components/IngestPage';
import ReviewDashboard from './components/ReviewDashboard';

function ProtectedRoute({ children, loggedIn }) {
  if (!loggedIn) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(isLoggedIn());

  function handleLogin() {
    setLoggedIn(true);
  }

  function handleLogout() {
    logout();
    setLoggedIn(false);
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            loggedIn
              ? <Navigate to="/" replace />
              : <LoginPage onLogin={handleLogin} />
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute loggedIn={loggedIn}>
              <IngestPage onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />
        <Route
          path="/review"
          element={
            <ProtectedRoute loggedIn={loggedIn}>
              <ReviewDashboard onLogout={handleLogout} />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
