import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import RoomList from '../components/rooms/RoomList';
import ReservationForm from '../components/reservations/ReservationForm';
import ReservationHistory from '../components/reservations/ReservationHistory';
import './EmployeeDashboardPage.css';

const EmployeeDashboardPage = ({ user, handleLogout }) => {
  const [rooms, setRooms] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [pendingRequests, setPendingRequests] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      try {
        if (!user || user.role !== 'employee') {
          navigate('/login', { replace: true });
          return;
        }

        // Fetch rooms
        const roomsResponse = await fetch('http://localhost:8080/api/salles/', {
          credentials: 'include',
        });
        if (!roomsResponse.ok) {
          if (roomsResponse.status === 401 || roomsResponse.status === 403) {
            throw new Error('Veuillez vous connecter pour accéder aux salles.');
          }
          throw new Error('Échec du chargement des salles.');
        }
        const roomsData = await roomsResponse.json();
        if (isMounted) {
          setRooms(roomsData);
        }

        // Fetch reservation history
        const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
          credentials: 'include',
        });
        if (!reservationsResponse.ok) {
          if (reservationsResponse.status === 401 || reservationsResponse.status === 403) {
            throw new Error('Veuillez vous connecter pour accéder à vos réservations.');
          }
          throw new Error('Échec du chargement des réservations.');
        }
        const reservationsData = await reservationsResponse.json();
        if (isMounted) {
          setReservations(reservationsData);
        }

        // Fetch pending reservations
        const pendingResponse = await fetch('http://localhost:8080/api/reservations/pending', {
          credentials: 'include',
        });
        if (!pendingResponse.ok) {
          if (pendingResponse.status === 401 || pendingResponse.status === 403) {
            throw new Error('Veuillez vous connecter pour accéder aux demandes en attente.');
          }
          throw new Error('Échec du chargement des demandes en attente.');
        }
        const pendingData = await pendingResponse.json();
        if (isMounted) {
          setPendingRequests(Array.isArray(pendingData) ? pendingData : []);
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message || 'Échec du chargement des données.');
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
    };
  }, [navigate, user]);

  const handleReservationCreated = async () => {
    try {
      const reservationsResponse = await fetch('http://localhost:8080/api/reservations/history', {
        credentials: 'include',
      });
      if (!reservationsResponse.ok) {
        throw new Error('Échec du chargement des réservations après création.');
      }
      const reservationsData = await reservationsResponse.json();
      setReservations(reservationsData);
    } catch (err) {
      setError('Erreur lors de la mise à jour de l’historique des réservations.');
    }
  };

  const handleRequestAction = async (requestId, action, priority = null) => {
    try {
      const payload = action === 'accept' && priority ? { status: 'approved', priority } : { status: action === 'accept' ? 'approved' : 'denied' };
      const response = await fetch(`http://localhost:8080/api/reservations/request/${requestId}/${action}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        if (response.status === 503) {
          throw new Error('Service temporairement indisponible. Veuillez réessayer plus tard.');
        }
        const errorData = await response.json();
        throw new Error(errorData.detail || `Échec de ${action === 'accept' ? "l'acceptation" : 'le refus'} de la demande.`);
      }

      setPendingRequests(pendingRequests.filter((request) => request.id !== requestId));
      alert(`Demande de réservation ${action === 'accept' ? 'acceptée' : 'refusée'} avec succès !`);
    } catch (err) {
      setError(err.message || `Erreur lors de ${action === 'accept' ? "l'acceptation" : 'le refus'} de la demande.`);
    }
  };

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

  if (!user) {
    return <div className="container">Redirection vers la connexion...</div>;
  }

  if (loading) {
    return <div className="container">Chargement...</div>;
  }

  return (
    <div className="container">
      <motion.div
        initial={{ opacity: 0, y: -50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
      >
        <div className="header">
          <h1>Tableau de Bord Employé</h1>
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

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.8 }}
          className="user-info"
        >
          <p>Bienvenue, {user.name} ({user.email})</p>
          <p>Rôle: {user.role}</p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4, duration: 0.8 }}
          className="section"
        >
          <h2>Salles Disponibles</h2>
          <RoomList rooms={rooms} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.8 }}
          className="section"
        >
          <h2>Demander une Réservation</h2>
          <ReservationForm rooms={rooms} onReservationCreated={handleReservationCreated} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8, duration: 0.8 }}
          className="section"
        >
          <h2>Historique des Réservations</h2>
          <ReservationHistory
            reservations={reservations}
            onReservationDeleted={() => {}}
            isAdmin={false}
          />
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.0, duration: 0.8 }}
          className="section"
        >
          <h2>Demandes de Réservation en Attente</h2>
          {pendingRequests.length === 0 ? (
            <p>Aucune demande en attente.</p>
          ) : (
            pendingRequests.map((request) => (
              <div key={request.id} className="request-item">
                <p>Salle: {request.room_name || "Unknown Room"}</p>
                <p>Début: {formatDate(request.start_time)}</p>
                <p>Fin: {formatDate(request.end_time)}</p>
                <p>Utilisateur: {request.user_id}</p>
                <div className="request-actions">
                  <select
                    className="priority-select"
                    onChange={(e) => {
                      const priority = parseInt(e.target.value);
                      handleRequestAction(request.id, 'accept', priority);
                    }}
                  >
                    <option value="">Sélectionner la priorité (si acceptée)</option>
                    <option value="1">Priorité 1</option>
                    <option value="2">Priorité 2</option>
                    <option value="3">Priorité 3</option>
                  </select>
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
      </motion.div>
    </div>
  );
};

export default EmployeeDashboardPage;