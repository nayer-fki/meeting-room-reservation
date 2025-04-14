import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Container, Row, Col, Card, Button, Form } from 'react-bootstrap';
import { motion } from 'framer-motion';
import { toast } from 'react-toastify';
import LoadingSpinner from '../components/LoadingSpinner'; // We'll use this now

const AdminDashboard = ({ token }) => {
  const [rooms, setRooms] = useState([]);
  const [newRoom, setNewRoom] = useState({ name: '', capacity: '', location: '' });
  const [reservations, setReservations] = useState([]);
  const [loading, setLoading] = useState(true); // Add loading state

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true); // Set loading to true before fetching
        const config = { headers: { Authorization: `Bearer ${token}` } };
        const roomsResponse = await axios.get('http://localhost:8080/api/rooms', config);
        const reservationsResponse = await axios.get('http://localhost:8080/api/reservations/all', config);
        setRooms(roomsResponse.data);
        setReservations(reservationsResponse.data);
      } catch (error) {
        console.error('Error fetching data:', error);
        toast.error('Failed to load data');
      } finally {
        setLoading(false); // Set loading to false after fetching
      }
    };
    fetchData();
  }, [token]);

  const handleAddRoom = async (e) => {
    e.preventDefault();
    try {
      setLoading(true); // Show spinner while adding room
      const config = { headers: { Authorization: `Bearer ${token}` } };
      await axios.post('http://localhost:8080/api/rooms', newRoom, config);
      const roomsResponse = await axios.get('http://localhost:8080/api/rooms', config);
      setRooms(roomsResponse.data);
      toast.success('Room added successfully');
      setNewRoom({ name: '', capacity: '', location: '' });
    } catch (error) {
      console.error('Error adding room:', error);
      toast.error('Failed to add room');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteRoom = async (roomId) => {
    try {
      setLoading(true); // Show spinner while deleting room
      const config = { headers: { Authorization: `Bearer ${token}` } };
      await axios.delete(`http://localhost:8080/api/rooms/${roomId}`, config);
      setRooms(rooms.filter((room) => room.id !== roomId));
      toast.success('Room deleted successfully');
    } catch (error) {
      console.error('Error deleting room:', error);
      toast.error('Failed to delete room');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <LoadingSpinner />; // Use LoadingSpinner while data is being fetched
  }

  return (
    <Container className="mt-5">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}>
        <h2>Admin Dashboard</h2>
        <Row>
          <Col md={6}>
            <h3>Add New Room</h3>
            <Form onSubmit={handleAddRoom}>
              <Form.Group className="mb-3">
                <Form.Label>Name</Form.Label>
                <Form.Control
                  type="text"
                  value={newRoom.name}
                  onChange={(e) => setNewRoom({ ...newRoom, name: e.target.value })}
                  required
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Capacity</Form.Label>
                <Form.Control
                  type="number"
                  value={newRoom.capacity}
                  onChange={(e) => setNewRoom({ ...newRoom, capacity: e.target.value })}
                  required
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Location</Form.Label>
                <Form.Control
                  type="text"
                  value={newRoom.location}
                  onChange={(e) => setNewRoom({ ...newRoom, location: e.target.value })}
                  required
                />
              </Form.Group>
              <Button type="submit" variant="primary">Add Room</Button>
            </Form>
          </Col>
          <Col md={6}>
            <h3>All Rooms</h3>
            {rooms.map((room) => (
              <Card key={room.id} className="mb-3">
                <Card.Body>
                  <Card.Title>{room.name}</Card.Title>
                  <Card.Text>
                    Capacity: {room.capacity}<br />
                    Location: {room.location}
                  </Card.Text>
                  <Button variant="danger" onClick={() => handleDeleteRoom(room.id)}>
                    Delete
                  </Button>
                </Card.Body>
              </Card>
            ))}
          </Col>
        </Row>
        <h3>All Reservations</h3>
        <Row>
          {reservations.map((reservation) => (
            <Col md={4} key={reservation.id} className="mb-3">
              <Card>
                <Card.Body>
                  <Card.Title>Reservation #{reservation.id}</Card.Title>
                  <Card.Text>
                    Room ID: {reservation.room_id}<br />
                    User ID: {reservation.user_id}<br />
                    Start: {new Date(reservation.start_time).toLocaleString()}<br />
                    End: {new Date(reservation.end_time).toLocaleString()}
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

export default AdminDashboard;