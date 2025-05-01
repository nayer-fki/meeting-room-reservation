// frontend/src/components/reservations/ReservationActions.js
import React, { useState } from 'react';
import './ReservationActions.css';

const ReservationActions = ({ reservations, onReservationUpdated }) => {
  const [error, setError] = useState(null);

  const handleStatusChange = async (reservationId, status) => {
    try {
      const response = await fetch(`http://localhost:8080/api/reservations/${reservationId}/status`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // Include cookies (JWT token)
        body: JSON.stringify({ status }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Non autorisé : veuillez vous reconnecter');
        } else if (response.status === 403) {
          throw new Error('Action non autorisée');
        } else {
          throw new Error('Échec de la mise à jour du statut');
        }
      }

      setError(null);
      onReservationUpdated();
    } catch (err) {
      setError(err.message);
      console.error('Failed to update reservation status:', err);
    }
  };

  const handlePriorityChange = async (reservationId, priority) => {
    try {
      const response = await fetch(`http://localhost:8080/api/reservations/${reservationId}/priority`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // Include cookies (JWT token)
        body: JSON.stringify({ priority }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Non autorisé : veuillez vous reconnecter');
        } else if (response.status === 403) {
          throw new Error('Action non autorisée');
        } else {
          throw new Error('Échec de la mise à jour de la priorité');
        }
      }

      setError(null);
      onReservationUpdated();
    } catch (err) {
      setError(err.message);
      console.error('Failed to update reservation priority:', err);
    }
  };

  return (
    <div className="reservation-actions">
      <h3>Actions sur les Réservations</h3>
      {error && <p className="form-error">{error}</p>}
      {reservations.length === 0 ? (
        <p className="no-data">Aucune réservation à gérer.</p>
      ) : (
        <table className="action-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Salle</th>
              <th>Utilisateur</th>
              <th>Statut</th>
              <th>Priorité</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {reservations.map((reservation) => (
              <tr key={reservation.id}>
                <td>{reservation.id}</td>
                <td>{reservation.room_name}</td>
                <td>{reservation.user_id}</td>
                <td>{reservation.status}</td>
                <td>{reservation.priority || 'N/A'}</td>
                <td>
                  <button
                    onClick={() => handleStatusChange(reservation.id, 'approved')}
                    className="approve-button"
                    disabled={reservation.status === 'approved'}
                  >
                    Approuver
                  </button>
                  <button
                    onClick={() => handleStatusChange(reservation.id, 'denied')}
                    className="deny-button"
                    disabled={reservation.status === 'denied'}
                  >
                    Refuser
                  </button>
                  <select
                    onChange={(e) => handlePriorityChange(reservation.id, parseInt(e.target.value))}
                    className="priority-select"
                    defaultValue=""
                  >
                    <option value="" disabled>
                      Sélectionner une priorité
                    </option>
                    <option value="1">1 (Faible)</option>
                    <option value="2">2</option>
                    <option value="3">3 (Élevée)</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default ReservationActions;