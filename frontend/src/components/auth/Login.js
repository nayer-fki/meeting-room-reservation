// frontend/src/components/auth/Login.js
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './Login.css';

const Login = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState(null);

  const fetchUser = async () => {
    setLoading(true);
    try {
      console.log('Fetching user data from /api/users/me in Login.js');
      const response = await fetch('http://localhost:8080/api/users/me', {
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error(`Failed to fetch user: ${response.status} ${response.statusText}`);
      }
      const data = await response.json();
      console.log('User data fetched in Login.js:', data);
      setUser(data.user);
      setLoading(false);

      // Redirect based on user role
      if (data.user.role === 'admin') {
        console.log('Redirecting to /admin-dashboard from Login.js');
        navigate('/admin-dashboard', { replace: true });
      } else if (data.user.role === 'employee' || data.user.role === 'visitor') {
        console.log('Redirecting to /employee-dashboard from Login.js');
        navigate('/employee-dashboard', { replace: true });
      }
    } catch (error) {
      console.error('Error fetching user in Login.js:', error.message);
      setUser(null);
      setLoading(false);
      // Stay on login page if fetch fails (user is not authenticated)
    }
  };

  useEffect(() => {
    fetchUser(); // Check if user is already authenticated on mount
  }, []);

  const handleLogin = () => {
    if (!user) {
      window.location.href = 'http://localhost:8080/api/login'; // Only redirect if not authenticated
    }
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (user) {
    return <div>Redirecting...</div>; // This should never render due to navigate
  }

  return (
    <div className="login-form">
      <button onClick={handleLogin} className="login-button">
        Se connecter avec Google
      </button>
    </div>
  );
};

export default Login;