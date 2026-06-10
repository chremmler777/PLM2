/**
 * NotificationBell - unread badge + dropdown feed of in-app notifications.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';

interface NotificationItem {
  id: number;
  title: string;
  body: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string | null;
}

export default function NotificationBell({ collapsed }: { collapsed: boolean }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  const { data: unread } = useQuery<{ count: number }>({
    queryKey: ['notifications-unread'],
    queryFn: async () => (await client.get('/v1/notifications/unread-count')).data,
    refetchInterval: 30_000,
  });

  const { data: notifications } = useQuery<NotificationItem[]>({
    queryKey: ['notifications'],
    queryFn: async () => (await client.get('/v1/notifications')).data,
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });

  const markRead = useMutation({
    mutationFn: async (id: number) => {
      await client.post(`/v1/notifications/${id}/read`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread'] });
    },
  });

  const markAllRead = useMutation({
    mutationFn: async () => {
      await client.post('/v1/notifications/read-all');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread'] });
    },
  });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const count = unread?.count ?? 0;

  const handleClick = (n: NotificationItem) => {
    if (!n.is_read) markRead.mutate(n.id);
    if (n.link) {
      setOpen(false);
      navigate(n.link);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 rounded-lg text-slate-300 hover:bg-slate-700 font-medium text-sm text-left flex items-center gap-2"
        title="Notifications"
      >
        <span className="relative">
          🔔
          {count > 0 && (
            <span className="absolute -top-1.5 -right-2 px-1 min-w-[1rem] text-center rounded-full bg-red-500 text-white text-[10px] font-bold">
              {count > 99 ? '99+' : count}
            </span>
          )}
        </span>
        {!collapsed && <span>Notifications</span>}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-80 z-50 bg-slate-700 border border-slate-600 rounded-lg shadow-xl">
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-600">
            <span className="text-sm font-semibold text-slate-200">Notifications</span>
            {count > 0 && (
              <button
                onClick={() => markAllRead.mutate()}
                className="text-xs text-blue-300 hover:text-blue-200"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {!notifications || notifications.length === 0 ? (
              <p className="px-3 py-4 text-slate-400 text-xs text-center">No notifications</p>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleClick(n)}
                  className={`w-full text-left px-3 py-2 border-b border-slate-600/50 last:border-b-0 hover:bg-slate-600 ${
                    n.is_read ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {!n.is_read && <span className="mt-1.5 w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />}
                    <div className="min-w-0">
                      <p className="text-slate-100 text-xs font-medium">{n.title}</p>
                      {n.body && <p className="text-slate-400 text-xs mt-0.5 line-clamp-2">{n.body}</p>}
                      {n.created_at && (
                        <p className="text-slate-500 text-[10px] mt-0.5">
                          {new Date(n.created_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
