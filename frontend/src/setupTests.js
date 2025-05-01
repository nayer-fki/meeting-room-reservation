// src/setupTests.js
import { setupServer } from 'msw/node';
import handlers from './handlers'; // Import your handlers

const server = setupServer(...handlers);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());