/**
 * UsersPage - Admin user management: list, create, edit role/state, reset password.
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;

interface UserRecord {
  id: number;
  email: string;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
}

const ROLES = ['admin', 'engineer', 'viewer'];

interface DepartmentRecord {
  id: number;
  name: string;
  is_active?: boolean;
}

function DepartmentsModal({ user, onClose }: { user: UserRecord; onClose: () => void }) {
  const queryClient = useQueryClient();

  const { data: allDepartments } = useQuery<DepartmentRecord[]>({
    queryKey: ['departments'],
    queryFn: async () => (await client.get('/v1/workflow-templates/departments')).data,
  });
  const { data: memberships } = useQuery<DepartmentRecord[]>({
    queryKey: ['user-departments', user.id],
    queryFn: async () => (await client.get(`/v1/users/${user.id}/departments`)).data,
  });

  const [selected, setSelected] = useState<Set<number> | null>(null);
  const effective = selected ?? new Set(memberships?.map((d) => d.id) ?? []);

  const saveMutation = useMutation({
    mutationFn: async () => {
      await client.put(`/v1/users/${user.id}/departments`, {
        department_ids: Array.from(effective),
      });
    },
    onSuccess: () => {
      toast.success('Departments updated');
      queryClient.invalidateQueries({ queryKey: ['user-departments', user.id] });
      onClose();
    },
    onError: (error: unknown) => {
      toast.error(errDetail(error) || 'Failed to update departments');
    },
  });

  const toggle = (id: number) => {
    const next = new Set(effective);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-sm w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100 mb-1">Departments</h2>
        <p className="text-slate-400 text-sm mb-4">{user.username} — drives their My Tasks queue</p>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {allDepartments?.filter((d) => d.is_active !== false).map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
              <input
                type="checkbox"
                checked={effective.has(d.id)}
                onChange={() => toggle(d.id)}
                className="accent-blue-600"
              />
              {d.name}
            </label>
          ))}
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function roleColor(role: string): string {
  const colors: Record<string, string> = {
    admin: 'bg-purple-900/50 text-purple-300',
    engineer: 'bg-amber-900/50 text-amber-300',
    viewer: 'bg-slate-600 text-slate-200',
  };
  return colors[role] || 'bg-slate-700 text-slate-300';
}

function SetPasswordModal({ userName, onSubmit, onClose }: {
  userName: string
  onSubmit: (password: string) => void
  onClose: () => void
}) {
  const [pw, setPw] = useState('')
  const canSubmit = pw.length >= 8
  const submit = () => { onSubmit(pw); onClose() }
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-slate-100 mb-3">Set password — {userName}</h2>
        <input type="password" autoFocus minLength={8}
          className="w-full rounded-lg px-3 py-2 text-sm bg-slate-700 border border-slate-600 text-slate-100"
          placeholder="New password (min 8 characters)"
          value={pw} onChange={(e) => setPw(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && canSubmit) submit() }} />
        <div className="flex justify-end gap-2 mt-4">
          <button className="px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 rounded" onClick={onClose}>Cancel</button>
          <button className="px-4 py-2 rounded-lg bg-sky-600 text-white text-sm disabled:opacity-50 hover:bg-sky-500"
            disabled={!canSubmit}
            onClick={submit}>Set password</button>
        </div>
      </div>
    </div>
  )
}

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    email: '',
    username: '',
    full_name: '',
    password: '',
    role: 'viewer',
  });

  const mutation = useMutation({
    mutationFn: async () => {
      await client.post('/v1/users', {
        ...form,
        full_name: form.full_name || null,
      });
    },
    onSuccess: () => {
      toast.success('User created');
      queryClient.invalidateQueries({ queryKey: ['users'] });
      onClose();
    },
    onError: (error: unknown) => {
      const detail = errDetail(error);
      toast.error(typeof detail === 'string' ? detail : 'Failed to create user');
    },
  });

  const canSubmit = form.email.includes('@') && form.username.length >= 3 && form.password.length >= 8;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-slate-100 mb-4">Create User</h2>
        <div className="space-y-3">
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            placeholder="Email *"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <input
            type="text"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            placeholder="Username * (min 3 characters)"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <input
            type="text"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            placeholder="Full name"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder="Password * (min 8 characters)"
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!canSubmit || mutation.isPending}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {mutation.isPending ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function UsersPage() {
  const queryClient = useQueryClient();
  const { userId } = useAuth();
  const [showCreate, setShowCreate] = useState(false);
  const [departmentsUser, setDepartmentsUser] = useState<UserRecord | null>(null);
  const [passwordModalUser, setPasswordModalUser] = useState<UserRecord | null>(null);

  const { data: users, isLoading, error } = useQuery<UserRecord[]>({
    queryKey: ['users'],
    queryFn: async () => (await client.get('/v1/users')).data,
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, ...patch }: { id: number; role?: string; is_active?: boolean; password?: string }) => {
      await client.patch(`/v1/users/${id}`, patch);
    },
    onSuccess: () => {
      toast.success('User updated');
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
    onError: (err: unknown) => {
      const detail = errDetail(err);
      toast.error(typeof detail === 'string' ? detail : 'Failed to update user');
    },
  });

  const resetPassword = (user: UserRecord) => {
    setPasswordModalUser(user);
  };

  const handlePasswordSubmit = (password: string) => {
    if (passwordModalUser) {
      updateMutation.mutate({ id: passwordModalUser.id, password });
      setPasswordModalUser(null);
    }
  };

  if (error) {
    return (
      <div className="p-6">
        <p className="text-red-400">Failed to load users — admin role required.</p>
      </div>
    );
  }

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100">Users</h1>
          <p className="text-slate-400 text-sm mt-1">Accounts and roles for this organization</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + Create User
        </button>
      </div>

      {isLoading ? (
        <p className="text-slate-400">Loading...</p>
      ) : (
        <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700 bg-slate-700/30">
                <th className="text-left px-4 py-3 font-medium">User</th>
                <th className="text-left px-4 py-3 font-medium">Email</th>
                <th className="text-left px-4 py-3 font-medium">Role</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-right px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users?.map((user) => {
                const isSelf = user.id === userId;
                return (
                  <tr key={user.id} className="border-b border-slate-700/50">
                    <td className="px-4 py-3">
                      <p className="text-slate-100 font-medium">
                        {user.username}
                        {isSelf && <span className="text-slate-500 text-xs ml-2">(you)</span>}
                      </p>
                      {user.full_name && <p className="text-slate-400 text-xs">{user.full_name}</p>}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{user.email}</td>
                    <td className="px-4 py-3">
                      <select
                        value={user.role}
                        disabled={isSelf || updateMutation.isPending}
                        onChange={(e) => updateMutation.mutate({ id: user.id, role: e.target.value })}
                        className={`rounded px-2 py-1 text-xs font-medium border-0 ${roleColor(user.role)} ${isSelf ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>{r}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${user.is_active ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
                        {user.is_active ? 'active' : 'deactivated'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button
                        onClick={() => setDepartmentsUser(user)}
                        className="px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
                      >
                        Departments
                      </button>
                      <button
                        onClick={() => resetPassword(user)}
                        className="px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
                      >
                        Reset Password
                      </button>
                      {!isSelf && (
                        <button
                          onClick={() => updateMutation.mutate({ id: user.id, is_active: !user.is_active })}
                          disabled={updateMutation.isPending}
                          className={`px-2 py-1 rounded text-xs font-medium ${
                            user.is_active
                              ? 'bg-red-600/80 hover:bg-red-600 text-white'
                              : 'bg-green-600/80 hover:bg-green-600 text-white'
                          }`}
                        >
                          {user.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
      {departmentsUser && <DepartmentsModal user={departmentsUser} onClose={() => setDepartmentsUser(null)} />}
      {passwordModalUser && <SetPasswordModal userName={passwordModalUser.username} onSubmit={handlePasswordSubmit} onClose={() => setPasswordModalUser(null)} />}
    </div>
  );
}
