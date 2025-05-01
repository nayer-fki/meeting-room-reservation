import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Route, Routes, useNavigate } from 'react-router-dom';
import Login from './pages/LoginPage';
import Index from './pages/Index';
import EmployeeDashboardPage from './pages/EmployeeDashboardPage';
import AdminDashboardPage from './pages/AdminDashboardPage';
import './App.css';

const AppRoutes = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      // Clear the JWT token cookie by setting it to an expired value
      document.cookie = 'jwt_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';

      // Clear user state
      setUser(null);

      // Redirect to login page
      navigate('/login', { replace: true });
    } catch (err) {
      console.error('Erreur lors de la déconnexion:', err);
      alert('Erreur lors de la déconnexion. Vous êtes déconnecté localement.');
      // Ensure redirection even if there's an error
      navigate('/login', { replace: true });
    }
  };

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await fetch('http://localhost:8080/api/users/me', {
          credentials: 'include',
        });
        if (!response.ok) {
          throw new Error('Échec de la récupération de l’utilisateur');
        }
        const data = await response.json();
        // Adjust based on API response structure
        const userData = data.user || data; // Handle both { user: {...} } and direct user object
        setUser(userData);

        // Redirect based on user role
        if (userData.role === 'admin') {
          navigate('/admin-dashboard', { replace: true });
        } else if (userData.role === 'employee') {
          navigate('/employee-dashboard', { replace: true });
        } else if (userData.role === 'visitor') {
          navigate('/index', { replace: true });
        } else {
          navigate('/login', { replace: true });
        }
      } catch (err) {
        console.error('Erreur lors de la récupération de l’utilisateur:', err);
        setUser(null);
        navigate('/login', { replace: true });
      } finally {
        setLoading(false);
      }
    };

    fetchUser();
  }, [navigate]);

  if (loading) {
    return <div className="loading">Chargement...</div>;
  }

  return (
    <Routes>
      <Route path="/login" element={<Login setUser={setUser} />} />
      <Route
        path="/"
        element={
          user ? (
            <Index user={user} handleLogout={handleLogout} />
          ) : (
            <div className="redirecting">Redirection vers la page de connexion...</div>
          )
        }
      />
      <Route
        path="/index"
        element={
          user && user.role === 'visitor' ? (
            <Index user={user} handleLogout={handleLogout} />
          ) : (
            <div className="unauthorized">Accès non autorisé ou redirection...</div>
          )
        }
      />
      <Route
        path="/employee-dashboard"
        element={
          user && user.role === 'employee' ? (
            <EmployeeDashboardPage user={user} handleLogout={handleLogout} />
          ) : (
            <div className="unauthorized">Accès non autorisé ou redirection...</div>
          )
        }
      />
      <Route
        path="/admin-dashboard"
        element={
          user && user.role === 'admin' ? (
            <AdminDashboardPage user={user} handleLogout={handleLogout} />
          ) : (
            <div className="unauthorized">Accès non autorisé ou redirection...</div>
          )
        }
      />
    </Routes>
  );
};

const App = () => (
  <Router>
    <AppRoutes />
  </Router>
);

export default App;