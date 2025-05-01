// frontend/src/pages/Index.js
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import RoomList from '../components/rooms/RoomList';
import SearchBar from '../components/shared/SearchBar';
import UserList from '../components/users/UserList';
import useDebounce from '../hooks/useDebounce';
import './Index.css';

const Index = ({ user, handleLogout }) => {
  const [users, setUsers] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [pendingRequests, setPendingRequests] = useState([]);
  const [filteredRooms, setFilteredRooms] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [capacityFilter, setCapacityFilter] = useState('');
  const [locationFilter, setLocationFilter] = useState('');
  const [reservationForm, setReservationForm] = useState({
    roomId: '',
    startTime: '',
    endTime: '',
  });
  const navigate = useNavigate();

  const debouncedSearchQuery = useDebounce(searchQuery, 300);

  const getMinDateTime = () => {
    const now = new Date();
    return now.toISOString().slice(0, 16);
  };

  useEffect(() => {
    const fetchData = async () => {
      try {
        if (!user) {
          navigate('/login', { replace: true });
          return;
        }

        const isAdmin = user.role === 'admin';
        const isVisitor = user.role === 'visitor';
        const isEmployee = user.role === 'employee';

        if (isAdmin) {
          try {
            const usersResponse = await fetch('http://localhost:8080/api/users/', {
              credentials: 'include',
            });
            if (!usersResponse.ok) {
              throw new Error('Failed to fetch users');
            }
            const usersData = await usersResponse.json();
            setUsers(Array.isArray(usersData) ? usersData : usersData.users || []);
          } catch (err) {
            console.error('Failed to load users:', err);
          }
        }

        const roomsResponse = await fetch('http://localhost:8080/api/salles/', {
          credentials: 'include',
        });
        if (!roomsResponse.ok) {
          throw new Error('Failed to fetch rooms');
        }
        const roomsData = await roomsResponse.json();
        setRooms(roomsData);
        setFilteredRooms(roomsData);

        if (isVisitor) {
          const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
            credentials: 'include',
          });
          if (!reservationsResponse.ok) {
            throw new Error('Failed to fetch reservations');
          }
          const reservationsData = await reservationsResponse.json();
          console.log('Reservations data:', reservationsData);
          setReservations(Array.isArray(reservationsData) ? reservationsData : []);
        }

        if (isEmployee) {
          const pendingResponse = await fetch('http://localhost:8080/api/reservations/pending', {
            credentials: 'include',
          });
          if (!pendingResponse.ok) {
            throw new Error('Failed to fetch pending reservations');
          }
          const pendingData = await pendingResponse.json();
          setPendingRequests(Array.isArray(pendingData) ? pendingData : []);
        }
      } catch (err) {
        setError('Failed to load data. Please ensure you are logged in.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [navigate, user]);

  useEffect(() => {
    let filtered = rooms;

    if (debouncedSearchQuery) {
      filtered = filtered.filter((room) =>
        room.name.toLowerCase().includes(debouncedSearchQuery.toLowerCase())
      );
    }

    if (capacityFilter) {
      filtered = filtered.filter((room) => room.capacity >= parseInt(capacityFilter));
    }

    if (locationFilter) {
      filtered = filtered.filter((room) =>
        room.location.toLowerCase().includes(locationFilter.toLowerCase())
      );
    }

    setFilteredRooms(filtered);
  }, [debouncedSearchQuery, capacityFilter, locationFilter, rooms]);

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('fr-FR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const handleReservationSubmit = async (e) => {
    e.preventDefault();
    try {
      const start = new Date(reservationForm.startTime);
      const end = new Date(reservationForm.endTime);
      if (end <= start) {
        throw new Error('La date de fin doit être postérieure à la date de début.');
      }

      const response = await fetch('http://localhost:8080/api/reservations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          room_id: reservationForm.roomId,
          start_time: reservationForm.startTime,
          end_time: reservationForm.endTime,
        }),
      });

      if (!response.ok) {
        if (response.status === 503) {
          throw new Error('Service temporairement indisponible. Veuillez réessayer plus tard.');
        }
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to submit reservation request');
      }

      alert('Demande de réservation soumise avec succès !');
      setReservationForm({ roomId: '', startTime: '', endTime: '' });

      // Refresh reservations after successful submission
      if (user.role === 'visitor') {
        const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
          credentials: 'include',
        });
        if (reservationsResponse.ok) {
          const reservationsData = await reservationsResponse.json();
          setReservations(Array.isArray(reservationsData) ? reservationsData : []);
        }
      }
    } catch (err) {
      setError(err.message || 'Erreur lors de la soumission de la demande de réservation.');
      console.error(err);
    }
  };

  const handleRequestAction = async (requestId, action) => {
    try {
      const response = await fetch(`http://localhost:8080/api/reservations/request/${requestId}/${action}`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        if (response.status === 503) {
          throw new Error('Service temporairement indisponible. Veuillez réessayer plus tard.');
        }
        const errorData = await response.json();
        throw new Error(errorData.detail || `Failed to ${action} reservation request`);
      }

      setPendingRequests(pendingRequests.filter((request) => request.id !== requestId));
      alert(`Demande de réservation ${action === 'accept' ? 'acceptée' : 'refusée'} avec succès !`);
    } catch (err) {
      setError(err.message || `Erreur lors de ${action === 'accept' ? "l'acceptation" : 'le refus'} de la demande.`);
      console.error(err);
    }
  };

  if (loading) {
    return <div className="container">Chargement...</div>;
  }

  if (!user) {
    return <div className="container">Redirecting to login...</div>;
  }

  return (
    <div className="container">
      <motion.div
        initial={{ opacity: 0, y: -50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
      >
        <div className="header">
          <h1>Gestion et Réservation des Salles de Réunion</h1>
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.8 }}
            onClick={handleLogout}
            className="logout-button"
          >
            Déconnexion
          </motion.button>
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="error"
          >
            {error}
          </motion.p>
        )}

        <div className="user-info">
          <p>
            Bienvenue, {user.name} ({user.email})
          </p>
          <p>Rôle: {user.role}</p>
        </div>

        {user.role === 'admin' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2, duration: 0.8 }}
            className="section"
          >
            <h2>Tous les Utilisateurs</h2>
            <UserList users={users} />
          </motion.div>
        )}

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4, duration: 0.8 }}
          className="section"
        >
          <h2>Toutes les Salles</h2>

          <div className="filter-bar">
            <SearchBar
              placeholder="Rechercher des salles par nom..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <input
              type="number"
              placeholder="Capacité Minimale"
              value={capacityFilter}
              onChange={(e) => setCapacityFilter(e.target.value)}
              className="filter-input"
            />
            <input
              type="text"
              placeholder="Filtrer par emplacement..."
              value={locationFilter}
              onChange={(e) => setLocationFilter(e.target.value)}
              className="filter-input"
            />
          </div>

          <RoomList rooms={filteredRooms} />
        </motion.div>

        {(user.role === 'visitor' || user.role === 'employee') && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.8 }}
            className="section"
          >
            <h2>Demande de Réservation</h2>
            <form onSubmit={handleReservationSubmit} className="reservation-form">
              <div className="form-group">
                <label htmlFor="roomId">Salle:</label>
                <select
                  id="roomId"
                  name="roomId"
                  value={reservationForm.roomId}
                  onChange={(e) =>
                    setReservationForm({ ...reservationForm, roomId: e.target.value })
                  }
                  required
                >
                  <option value="">Sélectionner une salle</option>
                  {rooms.map((room) => (
                    <option key={room.id} value={room.id}>
                      {room.name} (Capacité: {room.capacity}, {room.location})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="startTime">Début:</label>
                <input
                  type="datetime-local"
                  id="startTime"
                  name="startTime"
                  value={reservationForm.startTime}
                  onChange={(e) =>
                    setReservationForm({ ...reservationForm, startTime: e.target.value })
                  }
                  min={getMinDateTime()}
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="endTime">Fin:</label>
                <input
                  type="datetime-local"
                  id="endTime"
                  name="endTime"
                  value={reservationForm.endTime}
                  onChange={(e) =>
                    setReservationForm({ ...reservationForm, endTime: e.target.value })
                  }
                  min={reservationForm.startTime || getMinDateTime()}
                  required
                />
              </div>
              <button type="submit" className="submit-button">
                Soumettre la Demande
              </button>
            </form>
          </motion.div>
        )}

        {user.role === 'visitor' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.8 }}
            className="section"
          >
            <h2>Vos Réservations</h2>
            {reservations.length === 0 ? (
              <p>Aucune réservation trouvée</p>
            ) : (
              reservations.map((reservation) => (
                <div key={reservation.id} className="reservation-item">
                  <p>Salle ID: {reservation.room_id}</p>
                  <p>Début: {formatDate(reservation.start_time)}</p>
                  <p>Fin: {formatDate(reservation.end_time)}</p>
                </div>
              ))
            )}
          </motion.div>
        )}

        {user.role === 'employee' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.8 }}
            className="section"
          >
            <h2>Demandes de Réservation en Attente</h2>
            {pendingRequests.length === 0 ? (
              <p>Aucune demande en attente</p>
            ) : (
              pendingRequests.map((request) => (
                <div key={request.id} className="request-item">
                  <p>Salle ID: {request.room_id}</p>
                  <p>Début: {formatDate(request.start_time)}</p>
                  <p>Fin: {formatDate(request.end_time)}</p>
                  <p>Utilisateur: {request.user_id}</p>
                  <div className="request-actions">
                    <button
                      onClick={() => handleRequestAction(request.id, 'accept')}
                      className="accept-button"
                    >
                      Accepter
                    </button>
                    <button
                      onClick={() => handleRequestAction(request.id, 'refuse')}
                      className="refuse-button"
                    >
                      Refuser
                    </button>
                  </div>
                </div>
              ))
            )}
          </motion.div>
        )}
      </motion.div>
    </div>
  );
};

export default Index;