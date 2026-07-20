/**
 * Axios HTTP client — shared-cookie SSO (AdminPanel hub).
 */
import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? '/plm2/api';

const client = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// On 401 (except the /auth/me probe) bounce to the hub login.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = (error.config?.url as string | undefined) ?? '';
    if (error.response?.status === 401 && !url.includes('/auth/me')) {
      window.location.href = '/';
    }
    return Promise.reject(error);
  }
);

export default client;
