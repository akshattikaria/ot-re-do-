"""Validate and repair a weekly timetable without silently dropping lectures.

Operational substitutions are per event; the optimiser's offering teacher remains
the default. All returned placements pass the same independent audit exposed by
the API. This is a deterministic, minimal-change heuristic, not an optimality claim.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy

import numpy as np

from .evaluator import _gaps

from .problem import Instance, Problem
from .schedule_state import ScheduleState


def checked_instance(data: dict) -> Instance:
    """Reject malformed input before indexing numpy arrays or scheduling."""
    inst = Instance.from_dict(data)
    if not inst.grid.days or not inst.grid.periods:
        raise ValueError('The time grid must contain days and periods')
    if len(inst.grid.days) > 7 or len(inst.grid.periods) > 24 or len(inst.events) > 1000:
        raise ValueError('The weekly grid or event count exceeds supported limits')
    if type(inst.grid.lunch_period) is not int or not 0 <= inst.grid.lunch_period < len(inst.grid.periods):
        raise ValueError('Invalid lunch period')
    for collection in (inst.groups, inst.faculty, inst.rooms, inst.offerings, inst.events):
        ids = [x.id for x in collection]
        if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('Entity IDs must be nonempty and unique within their type')
    if not all((inst.groups, inst.faculty, inst.rooms, inst.offerings, inst.events)):
        raise ValueError('Groups, teachers, rooms, offerings and events are required')
    T = len(inst.grid.days) * len(inst.grid.periods)
    for entity in [*inst.groups, *inst.faculty, *inst.rooms]:
        if any(type(t) is not int or not 0 <= t < T for t in entity.unavailable):
            raise ValueError(f'Invalid unavailable period for {entity.id}')
    for f in inst.faculty:
        if any(type(v) is not int or not 0 <= v <= T for v in (f.max_daily, f.max_weekly)):
            raise ValueError(f'Invalid load limits for {f.id}')
    if any(type(r.capacity) is not int or r.capacity <= 0 for r in inst.rooms):
        raise ValueError('Room capacities must be positive integers')
    gids, fids, oids = ({x.id for x in items} for items in (inst.groups, inst.faculty, inst.offerings))
    for o in inst.offerings:
        if not o.group_ids or not set(o.group_ids) <= gids or len(set(o.group_ids)) != len(o.group_ids):
            raise ValueError(f'Invalid groups for {o.id}')
        if not set(o.eligible_faculty) <= fids or len(set(o.eligible_faculty)) != len(o.eligible_faculty):
            raise ValueError(f'Invalid eligible teachers for {o.id}')
        if o.type not in ('theory', 'tutorial', 'lab'):
            raise ValueError(f'Invalid offering type for {o.id}')
    for e in inst.events:
        if e.offering_id not in oids or type(e.length) is not int or not 1 <= e.length <= len(inst.grid.periods):
            raise ValueError(f'Invalid event {e.id}')
        if type(e.headcount) is not int or e.headcount <= 0:
            raise ValueError(f'Invalid headcount for {e.id}')
    return inst


def audit(data: dict, solution: dict) -> dict:
    inst = checked_instance(data)
    events = {e.id: e for e in inst.events}
    offerings = {o.id: o for o in inst.offerings}
    faculty = {f.id: f for f in inst.faculty}
    rooms = {r.id: r for r in inst.rooms}
    groups = {g.id: g for g in inst.groups}
    P, D = len(inst.grid.periods), len(inst.grid.days)
    issues = []
    def issue(code, ids, message):
        issues.append({'code': code, 'eventIds': sorted(set(ids)), 'message': message})
    seen = set()
    occ = defaultdict(list)
    weekly, daily, theory = Counter(), Counter(), defaultdict(list)
    for a in solution.get('assignments', []):
        eid = a.get('eventId')
        if eid not in events:
            issue('unknown_event', [str(eid)], 'Unknown event in timetable')
            continue
        if eid in seen:
            issue('duplicate_event', [eid], 'Lecture is assigned more than once')
            continue
        seen.add(eid)
        e = events[eid]
        o = offerings[e.offering_id]
        fid = a.get('facultyId', solution.get('facultyOf', {}).get(o.id))
        r = rooms.get(a.get('roomId'))
        f = faculty.get(fid)
        d, p = a.get('day'), a.get('period')
        if type(d) is not int or type(p) is not int or not 0 <= d < D or not 0 <= p <= P-e.length or p <= inst.grid.lunch_period < p+e.length:
            issue('invalid_time', [eid], 'Lecture crosses lunch or lies outside the weekly grid')
            continue
        if not f or fid not in o.eligible_faculty:
            issue('ineligible_teacher', [eid], 'Teacher is not eligible for this subject')
        want = 'lab' if o.type == 'lab' else 'classroom'
        if not r or r.capacity < e.headcount or not (r.type == want or want == 'classroom' and r.type == 'hall'):
            issue('invalid_room', [eid], 'Room type or capacity does not fit the lecture')
        for offset in range(e.length):
            t = d*P+p+offset
            for kind, resource in [('teacher', fid), ('room', a.get('roomId')), *[('student', g) for g in o.group_ids]]:
                occ[(kind, resource, t)].append(eid)
            for gid in o.group_ids:
                if t in groups[gid].unavailable:
                    issue('group_unavailable', [eid], f'{groups[gid].name} is unavailable (interview or other fixed activity)')
            if f and t in f.unavailable:
                issue('teacher_unavailable', [eid], f'{f.name} is unavailable')
            if r and t in r.unavailable:
                issue('room_unavailable', [eid], f'{r.name} is unavailable')
        weekly[fid] += e.length
        daily[(fid, d)] += e.length
        if o.type != 'lab':
            theory[(o.id, d)].append(eid)
    for (kind, resource, t), ids in occ.items():
        if len(ids) > 1:
            issue(kind+'_clash', ids, f'{kind.title()} {resource} is double-booked on {inst.grid.days[t//P]}, period {t%P+1}')
    for fid, load in weekly.items():
        if fid in faculty and load > faculty[fid].max_weekly:
            ids = [a['eventId'] for a in solution['assignments'] if a['eventId'] in events and a.get('facultyId', solution.get('facultyOf', {}).get(events[a['eventId']].offering_id)) == fid]
            issue('weekly_overload', ids, f'{faculty[fid].name}: {load} periods exceeds weekly limit {faculty[fid].max_weekly}')
    for (fid, d), load in daily.items():
        if fid in faculty and load > faculty[fid].max_daily:
            ids = [eid for (kind, resource, t), es in occ.items() if kind == 'teacher' and resource == fid and t//P == d for eid in es]
            issue('daily_overload', ids, f'{faculty[fid].name}: daily limit exceeded on {inst.grid.days[d]}')
    for ids in theory.values():
        if len(ids) > 1:
            issue('same_day_theory', ids, 'Multiple theory sessions of the same offering on one day')
    missing = sorted(set(events)-seen)
    clash_codes = {'teacher_clash', 'room_clash', 'student_clash'}
    return {'valid': not issues and not missing, 'collisionFree': not any(i['code'] in clash_codes for i in issues),
            'complete': not missing, 'issues': issues, 'unscheduledEventIds': missing,
            'scheduledCount': len(seen), 'totalCount': len(events)}


def repair_timetable(data: dict, solution: dict, leaves: list[dict], cancellations: list[dict]) -> dict:
    data = deepcopy(data)
    inst = checked_instance(data)
    fids = {f.id for f in inst.faculty}
    E = {e.id: i for i, e in enumerate(inst.events)}
    T = len(inst.grid.days)*len(inst.grid.periods)
    for leave in leaves:
        if leave['facultyId'] not in fids or not leave['slots'] or any(type(t) is not int or not 0 <= t < T for t in leave['slots']):
            raise ValueError('Select a known teacher and at least one valid leave period')
        f = next(f for f in inst.faculty if f.id == leave['facultyId'])
        f.unavailable = sorted(set(f.unavailable) | set(leave['slots']))
    canceled = {c['eventId']: c.get('reason', '').strip() for c in cancellations}
    if len(canceled) != len(cancellations) or not set(canceled) <= set(E):
        raise ValueError('Cancellation IDs must identify distinct known lectures')
    # Reject malformed original placements rather than guessing what they meant.
    original_audit = audit(inst.to_dict(), solution)
    causes = defaultdict(list)
    for issue in original_audit['issues']:
        for eid in issue['eventIds']:
            if issue['message'] not in causes[eid]:
                causes[eid].append(issue['message'])
    structural = {'unknown_event', 'duplicate_event', 'invalid_time', 'invalid_room'}
    if any(i['code'] in structural for i in original_audit['issues']):
        raise ValueError('Fix invalid or duplicate lecture placements before repairing')
    prob = Problem(inst)
    state = ScheduleState(prob)
    fi = {f.id: i for i, f in enumerate(inst.faculty)}
    ri = {r.id: i for i, r in enumerate(inst.rooms)}
    originals = {a['eventId']: a for a in solution.get('assignments', [])}
    assigned, todo, changes = {}, [], []
    def teacher(a, e):
        return a.get('facultyId', solution.get('facultyOf', {}).get(inst.events[e].offering_id))
    def fits(e, t, r, f):
        return (f in prob.off_elig[prob.ev_off[e]] and state.fac_load[f]+prob.ev_len[e] <= prob.fac_max[f]
                and t in prob.valid_starts[e] and r in prob.valid_rooms[e] and state.fits(e,t,r,f))
    def place(e,t,r,f):
        state.place(e,t,r,f)
        state.fac_load[f] += prob.ev_len[e]
        assigned[inst.events[e].id] = {'eventId': inst.events[e].id, 'day': int(t//prob.P), 'period': int(t%prob.P), 'roomId': inst.rooms[r].id, 'facultyId': inst.faculty[f].id}
    # Preserve original placements wherever possible; remove impacted lectures first.
    for e, ev in enumerate(inst.events):
        a = originals.get(ev.id)
        if a:
            f = fi.get(teacher(a,e))
            t, r = a['day']*prob.P+a['period'], ri[a['roomId']]
            if ev.id not in canceled and f is not None and fits(e,t,r,f):
                place(e,t,r,f)
                continue
        todo.append(e)
    # Most constrained lectures first; deterministic ties preserve repeatability.
    todo.sort(key=lambda e: (len(prob.off_elig[prob.ev_off[e]])*len(prob.valid_starts[e])*len(prob.valid_rooms[e]), e))
    pending = []
    for e in todo:
        ev = inst.events[e]
        a = originals.get(ev.id)
        old_f = fi.get(teacher(a,e)) if a else None
        old_t = a['day']*prob.P+a['period'] if a else None
        candidates = []
        for f in prob.off_elig[prob.ev_off[e]]:
            if state.fac_load[f]+prob.ev_len[e] > prob.fac_max[f]:
                continue
            ts, rs = state.options(e,int(f))
            for t,r in zip(ts,rs):
                # A cancelled occurrence cannot be silently reinstated in the same period.
                if ev.id in canceled and t == old_t:
                    continue
                score = (0 if t == old_t else 1, 0 if f == old_f else 1,
                         0 if a and t//prob.P == a['day'] else 1,
                         abs(int(t)-(old_t or 0)), 0 if a and inst.rooms[r].id == a['roomId'] else 1, int(t),int(r),int(f))
                candidates.append((score,int(t),int(r),int(f)))
        if candidates:
            _,t,r,f = min(candidates)
            place(e,t,r,f)
            action = 'substituted' if t == old_t and f != old_f else 'rescheduled' if a else 'scheduled'
            changes.append({'eventId':ev.id,'action':action,'before':a,'after':assigned[ev.id], 'reason':canceled.get(ev.id) or '; '.join(causes[ev.id]) or 'Schedule a pending lecture in a valid make-up slot'})
        else:
            reason = 'No eligible teacher, room and time satisfy all hard constraints. Manual review is required; this heuristic does not prove infeasibility.'
            pending.append({'eventId':ev.id,'reason':reason,'cancellationReason':canceled.get(ev.id,'')})
            changes.append({'eventId':ev.id,'action':'unresolved','before':a,'after':None,'reason':reason})
    result = deepcopy(solution)
    result.update(id='managed', assignments=[assigned[e.id] for e in inst.events if e.id in assigned], onFront=False)
    # Optimisation scores do not describe a repaired or partial schedule.
    result.pop('metrics',None)
    result['violation'] = 0
    report = audit(inst.to_dict(),result)
    if report['issues']:
        raise RuntimeError('Internal repair validation failed')
    # Recompute the objective values for the actual event-level teachers. A
    # substitute need not teach every session of the original offering.
    gb = state.grp_occ.reshape(prob.G,prob.D,prob.P) > 0
    fb = state.fac_occ.reshape(prob.F,prob.D,prob.P) > 0
    lengths = sum(inst.events[E[eid]].length for eid in assigned)
    waste = sum(inst.events[E[eid]].length * (inst.rooms[ri[a['roomId']]].capacity-inst.events[E[eid]].headcount) / inst.rooms[ri[a['roomId']]].capacity for eid,a in assigned.items())
    result['objectives'] = {'f1':float(_gaps(gb,prob.lunch).sum()+0.5*_gaps(fb,prob.lunch).sum()),
                            'f2':float(waste/max(lengths,1)),
                            'f3':float(np.std(state.fac_load / np.maximum(prob.fac_max,1)))}
    return {'instance': inst.to_dict(), 'solution':result,'audit':report,'changes':changes,'pending':pending,
            'leaves':leaves,'cancellations':cancellations}
