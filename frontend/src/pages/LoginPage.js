// frontend/src/pages/LoginPage.js
import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Login from '../components/auth/Login';
import './LoginPage.css';

const LoginPage = ({ setUser }) => {
  const navigate = useNavigate();

  // Check if the user is already logged in or redirected back after authentication
  useEffect(() => {
    const checkUser = async () => {
      try {
        const response = await fetch('http://localhost:8080/api/users/me', {
          credentials: 'include',
        });
        if (response.ok) {
          const userData = await response.json();
          const user = userData.user || userData; // Handle response structure
          setUser(user); // Update user state in App.js
          // Redirect based on user role
          if (user.role === 'employee') {
            navigate('/employee-dashboard', { replace: true });
          } else if (user.role === 'admin') {
            navigate('/admin-dashboard', { replace: true });
          } else if (user.role === 'visitor') {
            navigate('/index', { replace: true });
          } else {
            navigate('/login', { replace: true });
          }
        }
      } catch (err) {
        console.error('Erreur lors de la vérification de l’utilisateur:', err);
        setUser(null); // Ensure user is null if fetch fails
      }
    };
    checkUser();
  }, [navigate, setUser]);

  return (
    <div className="login-page">
      <div className="login-container">
        <h1>Connexion</h1>
        <Login />
      </div>
    </div>
  );
};

export default LoginPage;