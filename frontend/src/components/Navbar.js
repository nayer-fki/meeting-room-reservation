import React from 'react';
import { Navbar as BootstrapNavbar, Nav, Button } from 'react-bootstrap';
import { Link, useNavigate } from 'react-router-dom';
import { FaSignOutAlt } from 'react-icons/fa';

const Navbar = ({ token, userRole, onLogout }) => {
  const navigate = useNavigate();

  const handleLogout = () => {
    onLogout();
    navigate('/');
  };

  return (
    <BootstrapNavbar bg="dark" variant="dark" expand="lg" className="mb-4">
      <BootstrapNavbar.Brand as={Link} to="/">Meeting Room Reservation</BootstrapNavbar.Brand>
      <BootstrapNavbar.Toggle aria-controls="basic-navbar-nav" />
      <BootstrapNavbar.Collapse id="basic-navbar-nav">
        <Nav className="me-auto">
          <Nav.Link as={Link} to="/">Home</Nav.Link>
          {token && <Nav.Link as={Link} to="/rooms">Rooms</Nav.Link>}
          {token && <Nav.Link as={Link} to="/reservations">Reservations</Nav.Link>}
          {token && userRole === 'admin' && <Nav.Link as={Link} to="/admin-dashboard">Admin Dashboard</Nav.Link>}
          {token && userRole === 'employee' && <Nav.Link as={Link} to="/employee-dashboard">Employee Dashboard</Nav.Link>}
        </Nav>
        <Nav>
          {token ? (
            <Button variant="outline-light" onClick={handleLogout}>
              <FaSignOutAlt /> Logout
            </Button>
          ) : (
            <Nav.Link as={Link} to="/login">Login</Nav.Link>
          )}
        </Nav>
      </BootstrapNavbar.Collapse>
    </BootstrapNavbar>
  );
};

export default Navbar;