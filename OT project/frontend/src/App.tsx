import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import ParetoExplorer from './pages/ParetoExplorer';
import Designer from './pages/Designer';
import TimetableManager from './pages/TimetableManager';
import { useStore } from './store';

const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

export default function App() {
  const source = useStore((s) => s.source);
  const repaired = useStore((s) => s.managedPlan?.baseSolutionId === s.selectedId);
  return (
    <div className="shell">
      <aside className="side">
        <div className="logo">Clockwork</div>
        <div className="logo-sub">Multi-objective timetabling</div>
        <nav className="nav">
          <NavLink to="/" end>
            <Icon d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z" />
            <span>Overview</span>
          </NavLink>
          <NavLink to="/pareto">
            <Icon d="M4 20V4M4 20h16M8 16l3-5 3 2 5-7" />
            <span>Pareto front</span>
          </NavLink>
          <NavLink to="/manage"><Icon d="M8 2v4M16 2v4M3 10h18M5 4h14v17H5zM8 14l3 3 5-5" /><span>Manage timetable</span></NavLink>
          <NavLink to="/designer">
            <Icon d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5S14 15 15 15h2a4 4 0 0 0 4-4c0-4.4-4-8-9-8zM7.5 11.5h.01M10 7.5h.01M15 7.5h.01" />
            <span>Designer</span>
          </NavLink>
        </nav>
        <div className="side-foot">
          {source === 'backend'
            ? 'Showing results from the Python optimiser (synthetic data).'
            : 'Showing built-in demo data. Start the Python server to run the real optimiser.'}
        </div>
      </aside>
      <main className="main">
        {repaired && <div className="card" role="status" style={{marginBottom: 16}}>A repaired weekly timetable is active. Review its changes and any unresolved lectures in <NavLink to="/manage">Manage timetable</NavLink>. Pareto statistics describe the original optimisation run.</div>}
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/pareto" element={<ParetoExplorer />} />
          <Route path="/manage" element={<TimetableManager />} />
          <Route path="/designer" element={<Designer />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}
