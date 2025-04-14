import React from 'react';
import { Spinner } from 'react-bootstrap';
import { motion } from 'framer-motion';

const LoadingSpinner = () => {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="d-flex justify-content-center align-items-center my-5"
    >
      <Spinner animation="border" variant="primary" />
      <span className="ms-2">Loading...</span>
    </motion.div>
  );
};

export default LoadingSpinner;