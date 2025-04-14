import React from 'react';

const Login = () => {
  const handleLogin = () => {
    console.log('Login button clicked, redirecting to http://localhost:8001/login');
    window.location.href = 'http://localhost:8001/login';
  };

  return (
    <div>
      <h2>Login</h2>
      <button onClick={handleLogin}>Login with Google</button>
    </div>
  );
};

export default Login;