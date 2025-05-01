// frontend/src/pages/AdminDashboardPage.js
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import RoomList from '../components/rooms/RoomList';
import RoomForm from '../components/rooms/RoomForm';
import ReservationHistory from '../components/reservations/ReservationHistory';
import ReservationActions from '../components/reservations/ReservationActions';
import UserList from '../components/users/UserList';
import './AdminDashboardPage.css';

const AdminDashboardPage = ({ user }) => {
  const [users, setUsers] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      try {
        // If user is not provided (shouldn't happen since App.js ensures authentication),
        // redirect to /login as a fallback
        if (!user) {
          console.log('No user provided, redirecting to /login');
          navigate('/login', { replace: true });
          return;
        }

        // Since App.js already ensures user.role === 'admin', no need to check role here

        // Fetch all users
        const usersResponse = await fetch('http://localhost:8080/api/users/', {
          credentials: 'include',
        });
        if (!usersResponse.ok) {
          throw new Error('Failed to fetch users');
        }
        const usersData = await usersResponse.json();
        setUsers(usersData);

        // Fetch all rooms
        const roomsResponse = await fetch('http://localhost:8080/api/salles/', {
          credentials: 'include',
        });
        if (!roomsResponse.ok) {
          throw new Error('Failed to fetch rooms');
        }
        const roomsData = await roomsResponse.json();
        setRooms(roomsData);

        // Fetch all reservations
        const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
          credentials: 'include',
        });
        if (!reservationsResponse.ok) {
          throw new Error('Failed to fetch reservations');
        }
        const reservationsData = await reservationsResponse.json();
        setReservations(reservationsData);
      } catch (err) {
        setError('Failed to load data');
        console.error(err);
      }
    };

    fetchData();
  }, [navigate, user]); // Depend on user prop

  const handleRoomCreated = async () => {
    try {
      const roomsResponse = await fetch('http://localhost:8080/api/salles/', {
        credentials: 'include',
      });
      if (!roomsResponse.ok) {
        throw new Error('Failed to fetch rooms');
      }
      const roomsData = await roomsResponse.json();
      setRooms(roomsData);
    } catch (err) {
      setError('Failed to refresh rooms');
      console.error(err);
    }
  };

  const handleReservationUpdated = async () => {
    try {
      const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
        credentials: 'include',
      });
      if (!reservationsResponse.ok) {
        throw new Error('Failed to fetch reservations');
      }
      const reservationsData = await reservationsResponse.json();
      setReservations(reservationsData);
    } catch (err) {
      setError('Failed to refresh reservations');
      console.error(err);
    }
  };

  return (
    <div className="container">
      <motion.div
        initial={{ opacity: 0, y: -50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
      >
        <h1>Tableau de Bord Administrateur</h1>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="error"
          >
            {error}
          </motion.p>
        )}

        {user && (
          <div className="user-info">
            <p>Bienvenue, {user.name} ({user.email})</p>
            <p>Rôle: {user.role}</p>
          </div>
        )}

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.8 }}
          className="section"
        >
          <h2>Créer une Nouvelle Salle</h2>
          <RoomForm onRoomCreated={handleRoomCreated} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4, duration: 0.8 }}
          className="section"
        >
          <h2>Toutes les Salles</h2>
          <RoomList rooms={rooms} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.8 }}
          className="section"
        >
          <h2>Tous les Utilisateurs</h2>
          <UserList users={users} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8, duration: 0.8 }}
          className="section"
        >
          <h2>Toutes les Réservations</h2>
          <ReservationHistory reservations={reservations} isAdmin={true} />
          <ReservationActions
            reservations={reservations}
            onReservationUpdated={handleReservationUpdated}
          />
        </motion.div>
      </motion.div>
    </div>
  );
};

export default AdminDashboardPage;