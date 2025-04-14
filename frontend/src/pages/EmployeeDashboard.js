import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Container, Row, Col, Card } from 'react-bootstrap';
// Removed unused imports: Table, Button, FaTrash, FaEdit, LoadingSpinner
import { motion } from 'framer-motion';
import { toast } from 'react-toastify';

const EmployeeDashboard = ({ token }) => {
  const [reservations, setReservations] = useState([]);
  // Removed unused 'rooms' state

  useEffect(() => {
    const fetchData = async () => {
      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };
        const reservationsResponse = await axios.get('http://localhost:8080/api/reservations', config);
        setReservations(reservationsResponse.data);
        // Removed unused rooms fetch
      } catch (error) {
        console.error('Error fetching data:', error);
        toast.error('Failed to load data');
      }
    };
    fetchData();
  }, [token]);

  return (
    <Container className="mt-5">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}>
        <h2>Employee Dashboard</h2>
        <h3>Your Reservations</h3>
        <Row>
          {reservations.map((reservation) => (
            <Col md={4} key={reservation.id} className="mb-3">
              <Card>
                <Card.Body>
                  <Card.Title>Reservation #{reservation.id}</Card.Title>
                  <Card.Text>
                    Room ID: {reservation.room_id}<br />
                    Start: {new Date(reservation.start_time).toLocaleString()}<br />
                    End: {new Date(reservation.end_time).toLocaleString()}<br />
                    Purpose: {reservation.purpose}
                  </Card.Text>
                </Card.Body>
              </Card>
            </Col>
          ))}
        </Row>
      </motion.div>
    </Container>
  );
};

export default EmployeeDashboard;