import React, { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const AuthCallback = ({ setToken, setUserRole }) => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    console.log('AuthCallback: Processing redirect...');
    const params = new URLSearchParams(location.search);
    const jwtToken = params.get('token');
    console.log('AuthCallback: Extracted jwt_token from URL:', jwtToken);

    if (jwtToken) {
      console.log('AuthCallback: JWT token found, saving to localStorage');
      localStorage.setItem('jwt_token', jwtToken);
      setToken(jwtToken);
      try {
        const payload = JSON.parse(atob(jwtToken.split('.')[1]));
        setUserRole(payload.role);
      } catch (error) {
        console.error('Error decoding token:', error);
      }
      console.log('AuthCallback: Navigating to /rooms');
      navigate('/rooms');
    } else {
      console.log('AuthCallback: No JWT token found, navigating to login');
      navigate('/login');
    }
  }, [location, navigate, setToken, setUserRole]);

  return <div>Processing authentication...</div>;
};

export default AuthCallback;