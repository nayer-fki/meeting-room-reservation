import { render, screen, waitFor } from '@testing-library/react';
import App from './App';

test('renders login page after loading', async () => {
  render(<App />);
  
  // Wait for the loading message to disappear
  await waitFor(() => {
    expect(screen.queryByText(/Chargement/i)).not.toBeInTheDocument();
  }, { timeout: 3000 });

  // Wait for the login page element to appear
  const loginPage = await screen.findByRole('button', { name: /login/i }, { timeout: 3000 });

  // Assert that the login page is in the document
  expect(loginPage).toBeInTheDocument();
});