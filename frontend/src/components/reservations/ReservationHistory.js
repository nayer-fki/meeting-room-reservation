// frontend/src/components/reservations/ReservationHistory.js
import React, { useState } from 'react';
import './ReservationHistory.css';

const ReservationHistory = ({ reservations, onReservationDeleted, isAdmin }) => {
  const [error, setError] = useState(null);

  const handleDelete = async (reservationId) => {
    try {
      const response = await fetch(`http://localhost:8080/api/reservations/${reservationId}`, {
        method: 'DELETE',
        credentials: 'include', // Include cookies (JWT token)
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Non autorisé : veuillez vous reconnecter');
        } else if (response.status === 403) {
          throw new Error('Action non autorisée');
        } else {
          throw new Error('Échec de la suppression de la réservation');
        }
      }

      setError(null); // Clear any previous errors
      onReservationDeleted();
    } catch (err) {
      setError(err.message);
      console.error('Failed to delete reservation:', err);
    }
  };

  return (
    <div className="reservation-table-container">
      {error && <p className="form-error">{error}</p>}
      <table className="reservation-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Salle</th>
            <th>Heure de Début</th>
            <th>Heure de Fin</th>
            <th>Statut</th>
            {!isAdmin && <th>Actions</th>}
          </tr>
        </thead>
        <tbody>
          {reservations.length === 0 ? (
            <tr>
              <td colSpan={isAdmin ? 5 : 6} className="no-data">
                Aucune réservation trouvée.
              </td>
            </tr>
          ) : (
            reservations.map((reservation) => (
              <tr key={reservation.id}>
                <td>{reservation.id}</td>
                <td>{reservation.room_name}</td>
                <td>{new Date(reservation.start_time).toLocaleString()}</td>
                <td>{new Date(reservation.end_time).toLocaleString()}</td>
                <td>{reservation.status}</td>
                {!isAdmin && (
                  <td>
                    <button
                      onClick={() => handleDelete(reservation.id)}
                      className="delete-button"
                    >
                      Supprimer
                    </button>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
};

export default ReservationHistory;