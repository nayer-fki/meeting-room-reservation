import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import 'bootstrap/dist/css/bootstrap.min.css';
import Login from './components/Login';
import AuthCallback from './components/AuthCallback';
import Index from './pages/Index';
import Rooms from './pages/Rooms';
import Reservations from './pages/Reservations';
import AdminDashboard from './pages/AdminDashboard';
import EmployeeDashboard from './pages/EmployeeDashboard';
import Navbar from './components/Navbar';

const App = () => {
  const [token, setToken] = useState(null);
  const [userRole, setUserRole] = useState(null);

  useEffect(() => {
    const storedToken = localStorage.getItem('jwt_token');
    if (storedToken) {
      setToken(storedToken);
      try {
        const payload = JSON.parse(atob(storedToken.split('.')[1]));
        setUserRole(payload.role);
      } catch (error) {
        console.error('Error decoding token:', error);
        localStorage.removeItem('jwt_token');
        setToken(null);
        setUserRole(null);
      }
    }
    console.log('App: Current token state:', storedToken);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('jwt_token');
    setToken(null);
    setUserRole(null);
    toast.success('Logged out successfully!');
  };

  return (
    <Router>
      <div>
        <Navbar token={token} userRole={userRole} onLogout={handleLogout} />
        <Routes>
          <Route path="/" element={<Index token={token} />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auth-callback" element={<AuthCallback setToken={setToken} setUserRole={setUserRole} />} />
          <Route
            path="/rooms"
            element={token ? <Rooms token={token} /> : <Navigate to="/login" />}
          />
          <Route
            path="/reservations"
            element={token ? <Reservations token={token} userRole={userRole} /> : <Navigate to="/login" />}
          />
          <Route
            path="/admin-dashboard"
            element={
              token && userRole === 'admin' ? (
                <AdminDashboard token={token} />
              ) : (
                <Navigate to={token ? "/" : "/login"} />
              )
            }
          />
          <Route
            path="/employee-dashboard"
            element={
              token && userRole === 'employee' ? (
                <EmployeeDashboard token={token} />
              ) : (
                <Navigate to={token ? "/" : "/login"} />
              )
            }
          />
        </Routes>
        <ToastContainer position="top-right" autoClose={3000} />
      </div>
    </Router>
  );
};

export default App;