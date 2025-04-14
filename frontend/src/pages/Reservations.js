import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Container, Row, Col, Form, Button, Table } from 'react-bootstrap';
// Removed unused imports: Card, LoadingSpinner
import { motion } from 'framer-motion';
import { toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

const Reservations = ({ token, userRole }) => {
  const [reservations, setReservations] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [newReservation, setNewReservation] = useState({
    room_id: '',
    start_time: '',
    end_time: '',
    purpose: '',
  });
  const [editingReservation, setEditingReservation] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const config = { headers: { Authorization: `Bearer ${token}` } };
        const roomsResponse = await axios.get('http://localhost:8080/api/rooms', config);
        const reservationsResponse = await axios.get('http://localhost:8080/api/reservations', config);
        setRooms(roomsResponse.data);
        setReservations(reservationsResponse.data);
      } catch (error) {
        console.error('Error fetching data:', error);
        toast.error('Failed to load data');
      }
    };
    fetchData();
  }, [token]);

  const handleCreateReservation = async (e) => {
    e.preventDefault();
    try {
      const config = { headers: { Authorization: `Bearer ${token}` } };
      await axios.post('http://localhost:8080/api/reservations', newReservation, config);
      const reservationsResponse = await axios.get('http://localhost:8080/api/reservations', config);
      setReservations(reservationsResponse.data);
      setNewReservation({ room_id: '', start_time: '', end_time: '', purpose: '' });
      toast.success('Reservation created successfully');
    } catch (error) {
      console.error('Error creating reservation:', error);
      toast.error('Failed to create reservation');
    }
  };

  const handleUpdateReservation = async (reservationId) => {
    try {
      const config = { headers: { Authorization: `Bearer ${token}` } };
      await axios.put(`http://localhost:8080/api/reservations/${reservationId}`, newReservation, config);
      const reservationsResponse = await axios.get('http://localhost:8080/api/reservations', config);
      setReservations(reservationsResponse.data);
      setEditingReservation(null);
      setNewReservation({ room_id: '', start_time: '', end_time: '', purpose: '' });
      toast.success('Reservation updated successfully');
    } catch (error) {
      console.error('Error updating reservation:', error);
      toast.error('Failed to update reservation');
    }
  };

  const handleDeleteReservation = async (reservationId) => {
    try {
      const config = { headers: { Authorization: `Bearer ${token}` } };
      await axios.delete(`http://localhost:8080/api/reservations/${reservationId}`, config);
      const reservationsResponse = await axios.get('http://localhost:8080/api/reservations', config);
      setReservations(reservationsResponse.data);
      toast.success('Reservation deleted successfully');
    } catch (error) {
      console.error('Error deleting reservation:', error);
      toast.error('Failed to delete reservation');
    }
  };

  const startEditing = (reservation) => {
    setEditingReservation(reservation.id);
    setNewReservation({
      room_id: reservation.room_id,
      start_time: reservation.start_time.slice(0, 16),
      end_time: reservation.end_time.slice(0, 16),
      purpose: reservation.purpose,
    });
  };

  return (
    <Container className="mt-5">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}>
        <h2>Manage Reservations</h2>
        <Row>
          <Col md={4}>
            <h3>{editingReservation ? 'Edit Reservation' : 'Create Reservation'}</h3>
            <Form onSubmit={(e) => (editingReservation ? handleUpdateReservation(editingReservation) : handleCreateReservation(e))}>
              <Form.Group className="mb-3">
                <Form.Label>Room</Form.Label>
                <Form.Control
                  as="select"
                  value={newReservation.room_id}
                  onChange={(e) => setNewReservation({ ...newReservation, room_id: e.target.value })}
                  required
                >
                  <option value="">Select a room</option>
                  {rooms.map((room) => (
                    <option key={room.id} value={room.id}>
                      {room.name}
                    </option>
                  ))}
                </Form.Control>
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Start Time</Form.Label>
                <Form.Control
                  type="datetime-local"
                  value={newReservation.start_time}
                  onChange={(e) => setNewReservation({ ...newReservation, start_time: e.target.value })}
                  required
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>End Time</Form.Label>
                <Form.Control
                  type="datetime-local"
                  value={newReservation.end_time}
                  onChange={(e) => setNewReservation({ ...newReservation, end_time: e.target.value })}
                  required
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Purpose</Form.Label>
                <Form.Control
                  type="text"
                  value={newReservation.purpose}
                  onChange={(e) => setNewReservation({ ...newReservation, purpose: e.target.value })}
                  required
                />
              </Form.Group>
              <Button type="submit" variant="primary">
                {editingReservation ? 'Update Reservation' : 'Create Reservation'}
              </Button>
              {editingReservation && (
                <Button variant="secondary" className="ms-2" onClick={() => setEditingReservation(null)}>
                  Cancel Edit
                </Button>
              )}
            </Form>
          </Col>
          <Col md={8}>
            <h3>Your Reservations</h3>
            <Table striped bordered hover>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Room ID</th>
                  <th>Start Time</th>
                  <th>End Time</th>
                  <th>Purpose</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {reservations.map((reservation) => (
                  <tr key={reservation.id}>
                    <td>{reservation.id}</td>
                    <td>{reservation.room_id}</td>
                    <td>{new Date(reservation.start_time).toLocaleString()}</td>
                    <td>{new Date(reservation.end_time).toLocaleString()}</td>
                    <td>{reservation.purpose}</td>
                    <td>{reservation.status}</td>
                    <td>
                      <Button variant="warning" size="sm" onClick={() => startEditing(reservation)} className="me-2">
                        Edit
                      </Button>
                      <Button variant="danger" size="sm" onClick={() => handleDeleteReservation(reservation.id)}>
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Col>
        </Row>
      </motion.div>
    </Container>
  );
};

export default Reservations;