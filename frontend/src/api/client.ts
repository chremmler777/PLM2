/**
 * Axios HTTP client — shared-cookie SSO (AdminPanel hub).
 */
import axios from 'axios';
import { ACTS_AS_HEADER, getActsAsDepartmentId } from '../lib/actsAs';
import { assertContained } from '../training/sandbox/containment';

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

// Training containment (frontend/src/training): while a training sandbox is
// open, a request on `client` that is not about to be answered by the
// sandbox's own adapter is refused here instead of reaching the live API. A
// no-op whenever no sandbox is open, which is always outside the training run.
client.interceptors.request.use((config) => {
  assertContained(config.url ?? '', config.adapter);
  return config;
});

/**
 * A second instance that always talks to the network, whatever `client` is doing.
 *
 * The training sandbox swaps `client.defaults.adapter` for the length of a
 * task, and a few requests still have to get out: identity and the training
 * record itself. Restoring the previous adapter and calling it is not an
 * option: on an axios.create instance `defaults.adapter` is the adapter
 * preference list, not a callable (caught in TWOS, 2026-08-04). Asking a
 * second, untouched instance is unambiguous. Nothing outside the sandbox uses
 * this.
 */
export const networkClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});
networkClient.interceptors.request.use((config) => {
  // The last thing before a request leaves the browser while a sandbox is up:
  // only the passthrough routes may.
  assertContained(config.url ?? '', undefined, true);
  return attachActsAs(config);
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
