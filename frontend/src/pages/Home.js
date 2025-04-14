import React, { useEffect, useState } from 'react';
import axios from 'axios';

const Home = () => {
  const [user, setUser] = useState(null);
  const token = localStorage.getItem('jwt_token');

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const response = await axios.get('http://localhost:8001/users/me', {
          headers: { Cookie: `jwt_token=${token}` },
          withCredentials: true, // Include cookies in the request
        });
        setUser(response.data.user);
      } catch (err) {
        console.error('Failed to fetch user:', err);
      }
    };
    fetchUser();
  }, [token]);

  return (
    <div>
      <h1>Welcome to Meeting Room Reservation</h1>
      {user ? (
        <div>
          <p>Welcome, {user.name}!</p>
          <p>Email: {user.email}</p>
          <p>Role: {user.role}</p>
        </div>
      ) : (
        <p>Loading user...</p>
      )}
    </div>
  );
};

export default Home;