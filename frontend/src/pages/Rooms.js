import React, { useState, useEffect } from 'react';
import axios from 'axios';
import axiosRetry from 'axios-retry';
import { Container, Row, Col, Card, Button } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import LoadingSpinner from '../components/LoadingSpinner';

// Configure axios-retry
axiosRetry(axios, {
  retries: 5, // Number of retry attempts
  retryDelay: (retryCount) => retryCount * 2000, // Exponential backoff: 2s, 4s, 6s, etc.
  retryCondition: (error) => {
    // Retry on network errors or 5xx status codes
    return axiosRetry.isNetworkOrIdempotentRequestError(error) || (error.response && error.response.status >= 500);
  },
});

const Rooms = ({ token }) => {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchRooms = async () => {
      try {
        const config = {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        };
        console.log('Request headers being sent:', config.headers);
        const response = await axios.get('http://localhost:8080/api/rooms', config);
        setRooms(response.data);
      } catch (error) {
        console.error('Failed to fetch rooms:', error);
        // Handle error appropriately (e.g., show an error message)
      } finally {
        setLoading(false);
      }
    };
    fetchRooms();
  }, [token]);

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <Container className="mt-5">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}>
        <h2>Available Rooms</h2>
        <Row>
          {rooms.map((room) => (
            <Col md={4} key={room.id} className="mb-4">
              <motion.div whileHover={{ scale: 1.05 }} transition={{ duration: 0.3 }}>
                <Card>
                  <Card.Img
                    variant="top"
                    src={`https://images.unsplash.com/photo-1581093450021-1a9b7e1e1e1e?ixlib=rb-4.0.3&auto=format&fit=crop&w=300&h=200`}
                    alt={room.name}
                  />
                  <Card.Body>
                    <Card.Title>{room.name}</Card.Title>
                    <Card.Text>
                      Capacity: {room.capacity}<br />
                      Location: {room.location}
                    </Card.Text>
                    <Button as={Link} to="/reservations" variant="primary">
                      Book Now
                    </Button>
                  </Card.Body>
                </Card>
              </motion.div>
            </Col>
          ))}
        </Row>
      </motion.div>
    </Container>
  );
};

export default Rooms;