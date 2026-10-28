import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { auditTimetable, repairTimetable } from '../api';
import { useStore } from '../store';
import type { Assignment, Cancellation, Instance, Leave, RepairPlan, Solution, TimetableAudit } from '../types';
import TimetablePoster from '../components/TimetablePoster';
import PosterFrame from '../components/PosterFrame';
import { aspects } from '../themes/designs';

const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function SlotPicker({ instance, slots, onChange, label }: { instance: Instance; slots: number[]; onChange: (slots: number[]) => void; label: string }) {
  const P = instance.grid.periods.length;
  return <fieldset className="slot-picker"><legend>{label}</legend>
    <div className="slot-scroll"><table><thead><tr><th scope="col">Period</th>{instance.grid.days.map((d) => <th scope="col" key={d}>{d}</th>)}</tr></thead>
      <tbody>{instance.grid.periods.map((p, pi) => <tr key={p}><th scope="row">{p}</th>{instance.grid.days.map((d, di) => {
        const slot = di * P + pi;
        return <td key={d}><input type="checkbox" aria-label={`${label}: ${d} ${p}`} checked={slots.includes(slot)} disabled={pi === instance.grid.lunchPeriod}
          onChange={() => onChange(slots.includes(slot) ? slots.filter((x) => x !== slot) : [...slots, slot].sort((a,b) => a-b))} /></td>;
      })}</tr>)}</tbody></table></div>
  </fieldset>;
}

function AuditSummary({ report }: { report: TimetableAudit | null }) {
  if (!report) return <p className="muted">Check the timetable to see collisions, availability conflicts and workload violations.</p>;
  return <div role="status">
    <div className="manage-badges"><span className={`chip ${report.collisionFree ? 'sage' : 'accent'}`}>{report.collisionFree ? 'No collisions' : 'Collisions detected'}</span>
      <span className={`chip ${report.valid ? 'sage' : 'accent'}`}>{report.valid ? 'All constraints satisfied' : 'Needs attention'}</span>
      <span className="chip">{report.scheduledCount}/{report.totalCount} lectures scheduled</span></div>
    {!!report.unscheduledEventIds.length && <p>{report.unscheduledEventIds.length} lecture(s) need a make-up slot. They are not counted as delivered.</p>}
    {!!report.issues.length && <ul className="issue-list">{report.issues.map((i, n) => <li key={n}><b>{i.message}</b><br/><small>{i.eventIds.join(', ')}</small></li>)}</ul>}
  </div>;
}

export default function TimetableManager() {
  const state = useStore();
  const base = state.solutions.find((s) => s.id === state.selectedId) ?? state.solutions[0];
  const active = state.managedPlan?.baseSolutionId === state.selectedId ? state.managedPlan : null;
  const currentInstance = active?.instance ?? state.instance;
  const currentSolution = active?.solution ?? base;
  // Remount all editable state when the selected source timetable changes.
  return <Manager key={`${state.selectedId}-${state.instance.name}-${state.source}-${state.stats?.runtime ?? 0}`} instance={currentInstance} solution={currentSolution} active={active}
    onApply={(plan) => state.applyRepair(plan, state.selectedId)} onReset={state.clearRepair} />;
}

function Manager({ instance, solution, active, onApply, onReset }: {
  instance: Instance; solution: Solution; active: RepairPlan | null; onApply: (plan: RepairPlan) => void; onReset: () => void;
}) {
  const { theme, view, setView, decorations, blockNotes, running, source } = useStore();
  const [draft, setDraft] = useState(() => copy(instance));
  const [teacherId, setTeacherId] = useState(instance.faculty[0].id);
  const [groupId, setGroupId] = useState(instance.groups[0].id);
  const [leaveSlots, setLeaveSlots] = useState<number[]>([]);
  const [leaves, setLeaves] = useState<Leave[]>([]);
  const [eventId, setEventId] = useState(solution.assignments[0]?.eventId ?? instance.events[0].id);
  const [reason, setReason] = useState('Interview / OA');
  const [cancellations, setCancellations] = useState<Cancellation[]>([]);
  const [plan, setPlan] = useState<RepairPlan | null>(null);
  const [report, setReport] = useState<TimetableAudit | null>(active?.audit ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const teacher = draft.faculty.find((f) => f.id === teacherId)!;
  const group = draft.groups.find((g) => g.id === groupId)!;
  const displayed = plan ?? active;
  const size = aspects.find((a) => a.id === theme.aspect)!;

  useEffect(() => { setDraft(copy(instance)); setReport(active?.audit ?? null); }, [instance, active]);
  const invalidate = () => { setPlan(null); setReport(null); setMessage(''); setError(''); };
  const edit = (next: Instance) => { invalidate(); setDraft(next); };
  const updateTeacher = (changes: Partial<Instance['faculty'][number]>) => edit({ ...draft, faculty: draft.faculty.map((f) => f.id === teacherId ? {...f, ...changes} : f) });
  const labelFor = (id: string) => {
    const event = draft.events.find((e) => e.id === id);
    const offering = draft.offerings.find((o) => o.id === event?.offeringId);
    return `${offering?.code ?? id} · ${offering?.groupIds.map((g) => draft.groups.find((x) => x.id === g)?.name).join(', ') ?? ''} · ${id}`;
  };
  const placement = (a: Assignment | null) => a ? `${draft.grid.days[a.day]} ${draft.grid.periods[a.period]}, ${draft.rooms.find((r) => r.id === a.roomId)?.name}, ${draft.faculty.find((f) => f.id === (a.facultyId ?? solution.facultyOf[draft.events.find((e) => e.id === a.eventId)!.offeringId]))?.name}` : 'Not scheduled';
  async function request(kind: 'audit' | 'repair') {
    setBusy(true); setError(''); setMessage('');
    try {
      if (kind === 'audit') {
        setReport(await auditTimetable(draft, solution));
        setPlan(null);
      } else {
        const result = await repairTimetable(draft, solution, leaves, cancellations);
        setPlan(result); setReport(result.audit);
      }
    } catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function regenerate() {
    setBusy(true); setError(''); setMessage(''); setPlan(null);
    try {
      await useStore.getState().runOptimizer(draft);
      const failure = useStore.getState().runError;
      if (failure) setError(failure);
      else setMessage('A new timetable was generated with your constraints. Review the new Pareto solutions from Overview.');
    } finally { setBusy(false); }
  }
  function apply() {
    if (!plan) return;
    onApply(plan); setPlan(null); setLeaves([]); setCancellations([]); setLeaveSlots([]);
    setMessage('Repair applied and saved in this browser. Designer and exports now use the repaired timetable.');
  }
  function download() {
    if (!displayed) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(displayed, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'clockwork-repair-plan.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <>
    <div className="page-head"><div><h1>Manage timetable</h1><p>Keep classes clash-free. Cover teacher leave and recover lectures missed for interviews or other fixed activities.</p></div><Link className="btn" to="/designer">Open designer</Link></div>
    <div className="card manage-intro"><b>Working week template</b><p>Availability applies to this weekly timetable, not a dated attendance record. Mark the full duration of an interview or leave. A make-up lecture is only scheduled where students, an eligible teacher and a suitable room are all free.</p>
      {source === 'demo' && <p className="muted">You are viewing synthetic demo data. Repairs and checks use the live Python server and may reveal conflicts in the demo. Run the optimiser from Overview for a generated timetable.</p>}
      <p className="tiny">Changes are kept in this browser; download the plan for a portable record. Preview before applying. Unresolved lectures remain explicitly pending.</p></div>
    <fieldset className="manage-editors" disabled={busy || running}><legend className="sr-only">Timetable constraints</legend><div className="manage-grid">
      <section className="card"><h2>Teacher constraints & leave</h2><label className="field">Teacher<select aria-label="Teacher" className="input" value={teacherId} onChange={(e) => {setTeacherId(e.target.value); setLeaveSlots([]);}}>{draft.faculty.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
        <div className="row"><label className="field">Max periods / day<input className="input" type="number" min="0" max={draft.grid.periods.length} value={teacher.maxDaily} onChange={(e) => updateTeacher({maxDaily: Math.max(0, Math.min(draft.grid.periods.length, Number(e.target.value)))})}/></label>
          <label className="field">Max periods / week<input className="input" type="number" min="0" max={draft.grid.days.length*draft.grid.periods.length} value={teacher.maxWeekly} onChange={(e) => updateTeacher({maxWeekly: Math.max(0, Math.min(draft.grid.days.length*draft.grid.periods.length, Number(e.target.value)))})}/></label></div>
        <SlotPicker instance={draft} slots={teacher.unavailable ?? []} label="Teacher unavailable" onChange={(unavailable) => updateTeacher({unavailable})}/>
        <details><summary>Eligible subjects / offerings</summary><p className="tiny">Only checked offerings can be taught or covered by this teacher.</p><div className="eligibility-list">{draft.offerings.map((o) => <label key={o.id}><input type="checkbox" checked={o.eligibleFaculty.includes(teacherId)} onChange={() => edit({...draft, offerings: draft.offerings.map((x) => x.id !== o.id ? x : {...x, eligibleFaculty: x.eligibleFaculty.includes(teacherId) ? x.eligibleFaculty.filter((id) => id !== teacherId) : [...x.eligibleFaculty, teacherId]})})}/>{o.code} · {o.groupIds.map((id) => draft.groups.find((g) => g.id === id)?.name).join(', ')}</label>)}</div></details>
        <details><summary>Record teacher leave</summary><SlotPicker instance={draft} slots={leaveSlots} label="Leave periods" onChange={setLeaveSlots}/>
          <button className="btn" disabled={!leaveSlots.length || busy} onClick={() => {invalidate(); setLeaves([...leaves, {facultyId:teacherId, slots:leaveSlots}]); setLeaveSlots([]);}}>Add leave to repair</button>
          {leaves.map((l,i) => <p key={i}>{draft.faculty.find((f) => f.id === l.facultyId)?.name}: {l.slots.length} periods <button className="btn" onClick={() => {invalidate(); setLeaves(leaves.filter((_,j) => i !== j));}}>Remove leave</button></p>)}</details>
      </section>
      <section className="card"><h2>Student interviews & cancellations</h2><label className="field">Class group<select aria-label="Class group" className="input" value={groupId} onChange={(e) => setGroupId(e.target.value)}>{draft.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
        <p className="muted">Block the periods when this class cannot attend. Every overlapping lecture, including a multi-period lab, will need a make-up slot.</p>
        <SlotPicker instance={draft} slots={group.unavailable ?? []} label="Students unavailable (interview / fixed activity)" onChange={(unavailable) => edit({...draft, groups: draft.groups.map((g) => g.id === groupId ? {...g, unavailable} : g)})}/>
        <details><summary>Cancel a specific lecture</summary><p className="tiny">For one cancelled occurrence, select its lecture below. If students are absent for a time window, also block that window above so another lecture is not placed there.</p>
          <label className="field">Lecture<select className="input" value={eventId} onChange={(e) => setEventId(e.target.value)}>{draft.events.map((e) => <option key={e.id} value={e.id}>{labelFor(e.id)}</option>)}</select></label>
          <label className="field">Reason<input className="input" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}/></label>
          <button className="btn" disabled={busy || cancellations.some((c) => c.eventId === eventId)} onClick={() => {invalidate(); setCancellations([...cancellations, {eventId, reason:reason.trim() || 'Cancelled lecture'}]);}}>Add cancellation</button>
          {cancellations.map((c) => <p key={c.eventId}>{labelFor(c.eventId)} — {c.reason} <button className="btn" onClick={() => {invalidate(); setCancellations(cancellations.filter((x) => x.eventId !== c.eventId));}}>Remove cancellation</button></p>)}</details>
      </section>
    </div></fieldset>
    <section className="card manage-results"><div className="row manage-actions"><button className="btn" disabled={busy || running} onClick={() => request('audit')}>Check constraints</button><button className="btn accent" disabled={busy || running} onClick={() => request('repair')}>{busy ? 'Checking timetable…' : 'Preview repair'}</button>
      <button className="btn" disabled={busy || running || !!leaves.length || !!cancellations.length} onClick={regenerate}>Re-optimise with constraints</button>
      {plan && <button className="btn accent" disabled={busy} onClick={apply}>Apply {plan.audit.complete ? 'repair' : 'partial repair'}{!plan.audit.complete ? ` (${plan.pending.length} pending)` : ''}</button>}
      {displayed && <button className="btn" onClick={download}>Download repair plan</button>}
      <button className="btn" disabled={busy || running} onClick={() => {onReset(); setDraft(copy(useStore.getState().instance)); setPlan(null); setReport(null); setLeaves([]); setLeaveSlots([]); setCancellations([]); setMessage('Restored the original timetable and constraints.');}}>Discard changes & restore original</button></div>
      {error && <p role="alert" className="manage-error">{error}</p>}{message && <p role="status">{message}</p>}
      <p className="tiny">Preview repair keeps existing valid lectures in place. Re-optimise searches a fresh timetable using your edited constraints and the search settings from Overview; add leave and cancellation requests through repair first.</p>
      <h2>{plan ? 'Repair preview — not yet applied' : active ? 'Applied repair' : 'Timetable checks'}</h2><AuditSummary report={report}/>
      {plan && !plan.audit.complete && <p className="manage-error">Partial repair: {plan.pending.length} lecture(s) could not be placed. Applying keeps these in the pending list; it does not mark them completed.</p>}
      {displayed && <><h3>Changes ({displayed.changes.length})</h3><p className="tiny">Eligible cover is preferred in the same period; otherwise use the nearest valid make-up slot. Existing valid lectures are kept in place. The heuristic can leave lectures pending even when a larger rearrangement could work.</p>
        {!displayed.changes.length && <p>No lecture placements needed changing.</p>}
        <div className="changes-list">{displayed.changes.map((c) => <article key={c.eventId}><b>{labelFor(c.eventId)}</b> <span className={`chip ${c.action === 'unresolved' ? 'accent' : 'sage'}`}>{c.action}</span><p>Before: {placement(c.before)}<br/>After: {placement(c.after)}</p><small>{c.reason}</small></article>)}</div>
        {!!displayed.pending.length && <div className="manage-error"><h3>Pending make-up lectures</h3><ul>{displayed.pending.map((p) => <li key={p.eventId}>{labelFor(p.eventId)}: {p.reason}</li>)}</ul></div>}
      </>}
    </section>
    <section className="card manage-results"><div className="row"><h2>{plan ? 'Preview timetable' : 'Current timetable'}</h2><label className="field">View<select className="input" value={view.kind} onChange={(e) => setView(e.target.value as 'group'|'faculty'|'room')}><option value="group">Class group</option><option value="faculty">Teacher</option><option value="room">Room</option></select></label><label className="field">Entity<select className="input" value={view.entityId} onChange={(e) => setView(view.kind, e.target.value)}>{(view.kind === 'group' ? draft.groups : view.kind === 'faculty' ? draft.faculty : draft.rooms).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label></div>
      <PosterFrame w={size.w} h={size.h} maxH={760}><TimetablePoster instance={displayed?.instance ?? draft} solution={displayed?.solution ?? solution} view={view} theme={theme} decorations={decorations} blockNotes={blockNotes}/></PosterFrame>
    </section>
  </>;
}
