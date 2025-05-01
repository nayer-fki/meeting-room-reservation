// frontend/src/components/rooms/RoomList.js
import React from 'react';
import { motion } from 'framer-motion';
import './RoomList.css';

const RoomList = ({ rooms }) => {
  return (
    <div className="room-grid">
      {rooms.length === 0 ? (
        <p className="no-data">Aucune salle disponible.</p>
      ) : (
        rooms.map((room) => (
          <motion.div
            key={room.id}
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="room-card"
          >
            <h3>{room.name}</h3>
            <p>Capacité: {room.capacity}</p>
            <p>Emplacement: {room.location}</p>
          </motion.div>
        ))
      )}
    </div>
  );
};

export default RoomList;