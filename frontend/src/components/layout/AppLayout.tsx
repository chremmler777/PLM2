/**
 * AppLayout - Main application layout with sidebar. While an admin sees PLM
 * as a person (act as person), a banner on top says so, with the way back.
 */

import Sidebar from './Sidebar';
import { ViewingAsBanner } from './ActsAsSwitch';
import { useAuth } from '../../contexts/AuthContext';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { actingAsUser } = useAuth();
  return (
    <div className="flex h-screen flex-col bg-slate-900">
      {actingAsUser && <ViewingAsBanner name={actingAsUser.name} />}
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <div className="flex-1 min-w-0 overflow-auto">{children}</div>
      </div>
    </div>
  );
}
