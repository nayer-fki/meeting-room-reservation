// frontend/src/components/rooms/RoomForm.js
import React, { useState } from 'react';
import './RoomForm.css';

const RoomForm = ({ onRoomCreated }) => {
  const [formData, setFormData] = useState({
    name: '',
    capacity: '',
    location: '',
  });
  const [error, setError] = useState(null);

  const handleInputChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch('http://localhost:8080/api/rooms/', {
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
          throw new Error('Échec de la création de la salle');
        }
      }

      setFormData({ name: '', capacity: '', location: '' });
      setError(null); // Clear any previous errors
      onRoomCreated();
    } catch (err) {
      setError(err.message);
      console.error(err);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="room-form">
      {error && <p className="form-error">{error}</p>}
      <div className="form-group">
        <label>Nom:</label>
        <input
          type="text"
          name="name"
          value={formData.name}
          onChange={handleInputChange}
          className="form-input"
          required
        />
      </div>
      <div className="form-group">
        <label>Capacité:</label>
        <input
          type="number"
          name="capacity"
          value={formData.capacity}
          onChange={handleInputChange}
          className="form-input"
          required
        />
      </div>
      <div className="form-group">
        <label>Emplacement:</label>
        <input
          type="text"
          name="location"
          value={formData.location}
          onChange={handleInputChange}
          className="form-input"
          required
        />
      </div>
      <button type="submit" className="submit-button">
        Créer la Salle
      </button>
    </form>
  );
};

export default RoomForm;