// src/handlers.js
import { rest } from 'msw';

export const handlers = [
  rest.get('/api/users/me', (req, res, ctx) => {
    return res(
      ctx.json({
        id: '123',
        username: 'testuser',
      })
    );
  }),
];