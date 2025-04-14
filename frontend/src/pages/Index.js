import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Container, Row, Col, Card, Button } from 'react-bootstrap';
import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';

const Index = ({ token }) => {
  const [rooms, setRooms] = useState([]);

  useEffect(() => {
    const fetchRooms = async () => {
      try {
        const response = await axios.get('http://localhost:8080/api/rooms', {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        setRooms(response.data);
      } catch (error) {
        console.error('Failed to fetch rooms:', error);
      }
    };
    fetchRooms();
  }, [token]);

  return (
    <Container className="mt-5">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1 }}>
        {/* Hero Section */}
        <div className="text-center mb-5">
          <motion.h1
            initial={{ y: -50 }}
            animate={{ y: 0 }}
            transition={{ duration: 0.5 }}
            className="display-4"
          >
            Welcome to Meeting Room Reservation
          </motion.h1>
          <motion.p
            initial={{ y: 50 }}
            animate={{ y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="lead"
          >
            Book your meeting rooms with ease and efficiency.
          </motion.p>
          {!token && (
            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ duration: 0.5, delay: 0.4 }}>
              <Button as={Link} to="/login" variant="primary" size="lg">
                Get Started
              </Button>
            </motion.div>
          )}
        </div>

        {/* Services Section */}
        <h2 className="text-center mb-4">Our Services</h2>
        <Row className="mb-5">
          <Col md={4}>
            <motion.div whileHover={{ scale: 1.05 }} transition={{ duration: 0.3 }}>
              <Card className="text-center">
                <Card.Body>
                  <Card.Title>Room Booking</Card.Title>
                  <Card.Text>Easily book meeting rooms for your team.</Card.Text>
                </Card.Body>
              </Card>
            </motion.div>
          </Col>
          <Col md={4}>
            <motion.div whileHover={{ scale: 1.05 }} transition={{ duration: 0.3 }}>
              <Card className="text-center">
                <Card.Body>
                  <Card.Title>Notifications</Card.Title>
                  <Card.Text>Receive updates on your reservations.</Card.Text>
                </Card.Body>
              </Card>
            </motion.div>
          </Col>
          <Col md={4}>
            <motion.div whileHover={{ scale: 1.05 }} transition={{ duration: 0.3 }}>
              <Card className="text-center">
                <Card.Body>
                  <Card.Title>Admin Management</Card.Title>
                  <Card.Text>Admins can manage rooms and reservations.</Card.Text>
                </Card.Body>
              </Card>
            </motion.div>
          </Col>
        </Row>

        {/* Available Rooms Section */}
        <h2 className="text-center mb-4">Available Rooms</h2>
        <Row>
          {rooms.map((room) => (
            <Col md={4} key={room.id} className="mb-4">
              <motion.div whileHover={{ scale: 1.05 }} transition={{ duration: 0.3 }}>
                <Card>
                  <Card.Img
                    variant="top"
                    src={`https://via.placeholder.com/300x200?text=${room.name}`}
                    alt={room.name}
                  />
                  <Card.Body>
                    <Card.Title>{room.name}</Card.Title>
                    <Card.Text>
                      Capacity: {room.capacity}<br />
                      Location: {room.location}
                    </Card.Text>
                    {token ? (
                      <Button as={Link} to="/reservations" variant="primary">
                        Book Now
                      </Button>
                    ) : (
                      <Button as={Link} to="/login" variant="primary">
                        Login to Book
                      </Button>
                    )}
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

export default Index;