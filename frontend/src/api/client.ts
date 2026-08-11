/**
 * Axios HTTP client — shared-cookie SSO (AdminPanel hub).
 */
import axios from 'axios';
import { ACTS_AS_HEADER, getActsAsDepartmentId } from '../lib/actsAs';

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? '/plm2/api';

const client = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

/**
 * Attach the admin's acting-as department to every request. One interceptor
 * carries it, so no call site has to know the feature exists. Non-admins never
 * have a value stored, and the backend 403s the header for them anyway.
 */
export function attachActsAs<T extends { headers?: Record<string, unknown> }>(config: T): T {
  const deptId = getActsAsDepartmentId();
  if (deptId != null) {
    config.headers = { ...(config.headers ?? {}), [ACTS_AS_HEADER]: String(deptId) };
  }
  return config;
}

client.interceptors.request.use(attachActsAs);

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
