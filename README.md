# Clockwork timetable project

The editable application source is in [`OT project/`](<OT project/>).
`OT project.zip` is the original uploaded archive and is retained as a reference;
it is **not** the updated application. Develop and run the extracted source.

## Start

Python 3.11+ and Node 18+ are required. For automatic setup, run `bash scripts/setup.sh`, then `bash scripts/dev.sh` from the repository root. The equivalent manual steps are:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 'OT project/requirements.txt'
cd 'OT project/frontend'
npm ci
npm run build
```

In one terminal, from `OT project/`:

```bash
../.venv/bin/python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

In another terminal, from `OT project/frontend/`:

```bash
npm run dev -- --host 127.0.0.1 --strictPort
```

The development frontend uses port 5173 and proxies `/api` to port 8000.
The frontend still has synthetic demo data when the API is offline; timetable
checks, repairs and real optimisation require the Python server.

## Requested improvements

Open **Manage timetable** after generating or selecting a timetable:

1. **No collisions:** Check constraints detects teacher, room and student clashes,
   duplicate lectures, invalid times/rooms, ineligible teachers, blocked periods,
   daily/weekly overload and repeated theory sessions of an offering in one day.
2. **Teacher leave:** Select the teacher and add leave periods. Preview repair
   first tries an eligible substitute in the same period, then a valid make-up
   slot. Substitution is per lecture; it does not change every session's teacher.
3. **Interviews / OA and cancelled lectures:** Select a class group and block the
   entire fixed activity window. All affected lectures are moved outside it,
   including labs that overlap part of the activity. Specific cancellations can
   also be entered with a reason; their original occurrence cannot simply be
   reinstated by that repair.
4. **Teacher constraints:** Edit unavailable periods, eligible offerings, maximum
   daily periods and maximum weekly periods. Preview a repair or re-optimise the
   full timetable with these constraints. Re-optimisation uses the search settings
   from Overview. Add outstanding leave/cancellation requests through repair first.

Review the before/after list, then **Apply repair**. The Designer and CSV/PNG
exports use the applied placements and substitute teachers. Download the JSON
repair plan for the constraints, placements, audit and pending lecture list.
**Discard changes & restore original** restores the selected original solution.

If the heuristic cannot place a lecture, it remains explicitly pending. Partial
repairs can be applied, but they are never labelled complete or all-valid. The
repair preserves existing valid lectures and is not an exact infeasibility proof;
full re-optimisation may find a better arrangement. All newly placed lectures
satisfy the hard rules and the whole returned schedule is independently audited.

### Scope and persistence

This is a **weekly timetable template**, using day/period availability. It is not
a dated attendance/leave system. A day selection applies to that weekday in the
current template. There are no additional college-specific rules.

Applied changes are saved in browser local storage with the source timetable;
they survive reloads in that browser. They are not a shared server database or
multi-user transaction. A new optimisation run starts a new timetable and clears
the previous applied repair on success. Export JSON before replacing a timetable
to retain its operational record. Original Pareto statistics describe the original
optimisation run; a repaired timetable is not a Pareto-front claim. Objective
values are recalculated for repaired placements, but partial timetable scores
should not be compared with a complete schedule.

## Validation

From `OT project/`, with the virtual environment active:

```bash
python -m tests.test_core
python -m tests.test_methods
python -m unittest tests.test_operations -v
cd frontend && npm run build
```

There are 12 original solver checks and 15 operational regression tests, including
real CP-SAT feasibility, collision repair, teacher substitution, multi-period labs,
student interview windows, cancellations, overload/eligibility rules, malformed
inputs, deterministic repair, and honest unresolved results.

HTTP endpoints: `POST /api/timetable/audit` accepts `{instance, solution}`;
`POST /api/timetable/repair` also accepts `leaves: [{facultyId, slots}]` and
`cancellations: [{eventId, reason}]`. Slot indices are `day * periodsPerDay + period`.
`POST /api/runs` optionally accepts an `instance` with edited constraints.
Invalid input returns HTTP 422. See the API's `/docs` for request schemas.

The original project's algorithm and experiment documentation is in
[`OT project/README.md`](<OT project/README.md>).
