// frontend/src/components/users/UserList.js
import React from 'react';
import { motion } from 'framer-motion';
import './UserList.css';

const UserList = ({ users }) => {
  return (
    <div className="user-grid">
      {users.length === 0 ? (
        <p className="no-data">Aucun utilisateur disponible.</p>
      ) : (
        users.map((user) => (
          <motion.div
            key={user.id}
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="user-card"
          >
            <p className="user-name">{user.name}</p>
            <p className="user-email">{user.email}</p>
            <p className="user-role">Rôle: {user.role}</p>
          </motion.div>
        ))
      )}
    </div>
  );
};

export default UserList;