import type { RunParams, RunProgress, RunResult, Instance, Solution, TimetableAudit, RepairPlan, Leave, Cancellation } from './types';

// Requests go to /api, which Vite proxies to the Python server on port 8000 (see vite.config.ts).
const BASE = '/api';

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function backendAvailable(): Promise<boolean> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 1500);
    const res = await fetch(`${BASE}/health`, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

/** Starts a run and polls it until it finishes, reporting progress along the way. */
export async function optimise(params: RunParams, onProgress: (p: RunProgress) => void, instance?: Instance): Promise<RunResult> {
  const { runId } = await json<{ runId: string }>(
    await fetch(`${BASE}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...params, instance }) }),
  );
  for (;;) {
    await new Promise((r) => setTimeout(r, 500));
    const st = await json<{ status: string; progress?: RunProgress; result?: RunResult; error?: string }>(await fetch(`${BASE}/runs/${runId}`));
    if (st.progress) onProgress(st.progress);
    if (st.status === 'done' && st.result) return st.result;
    if (st.status === 'error') throw new Error(st.error ?? 'Optimiser failed');
  }
}

export async function auditTimetable(instance: Instance, solution: Solution): Promise<TimetableAudit> {
  return json(await fetch(`${BASE}/timetable/audit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instance, solution }) }));
}
export async function repairTimetable(instance: Instance, solution: Solution, leaves: Leave[], cancellations: Cancellation[]): Promise<RepairPlan> {
  return json(await fetch(`${BASE}/timetable/repair`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instance, solution, leaves, cancellations }) }));
}
