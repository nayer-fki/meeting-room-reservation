// frontend/src/components/reservations/ReservationForm.js
import React, { useState } from 'react';
import './ReservationForm.css';

const ReservationForm = ({ rooms, onReservationCreated }) => {
  const [formData, setFormData] = useState({
    room_id: '',
    start_time: '',
    end_time: '',
  });
  const [error, setError] = useState(null);

  const handleInputChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch('http://localhost:8080/api/reservations/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // Include cookies (JWT token)
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Non autorisé : veuillez vous reconnecter');
        } else if (response.status === 400) {
          throw new Error('Données invalides : vérifiez les champs');
        } else {
          throw new Error('Échec de la création de la réservation');
        }
      }

      setFormData({ room_id: '', start_time: '', end_time: '' });
      setError(null); // Clear any previous errors
      onReservationCreated();
    } catch (err) {
      setError(err.message);
      console.error(err);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="reservation-form">
      {error && <p className="form-error">{error}</p>}
      <div className="form-group">
        <label>Salle:</label>
        <select
          name="room_id"
          value={formData.room_id}
          onChange={handleInputChange}
          className="form-input"
          required
        >
          <option value="">Sélectionner une salle</option>
          {rooms.map((room) => (
            <option key={room.id} value={room.id}>
              {room.name}
            </option>
          ))}
        </select>
      </div>
      <div className="form-group">
        <label>Heure de Début:</label>
        <input
          type="datetime-local"
          name="start_time"
          value={formData.start_time}
          onChange={handleInputChange}
          className="form-input"
          required
        />
      </div>
      <div className="form-group">
        <label>Heure de Fin:</label>
        <input
          type="datetime-local"
          name="end_time"
          value={formData.end_time}
          onChange={handleInputChange}
          className="form-input"
          required
        />
      </div>
      <button type="submit" className="submit-button">
        Soumettre la Réservation
      </button>
    </form>
  );
};

export default ReservationForm;