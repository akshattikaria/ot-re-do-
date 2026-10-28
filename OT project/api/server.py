"""Web API for the Clockwork frontend.

Run:  python -m uvicorn api.server:app --reload --port 8000   (from the project root)

Optimisation runs take seconds to minutes, so they run as background jobs:
  POST /api/runs          start a run, returns {"runId": ...}
  GET  /api/runs/{id}     status + live progress; includes the result when done
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.instance_generator import SCENARIOS, generate
from src.runner import RunParams, run
from src.operations import audit, checked_instance, repair_timetable

app = FastAPI(title="Clockwork timetable optimiser", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()
MAX_JOBS_KEPT = 20


class RunRequest(BaseModel):
    scenario: str = Field("demo", description="demo | small | medium | large")
    instanceSeed: int = 1
    seed: int = 1
    popSize: int = Field(60, ge=10, le=300)
    generations: int = Field(40, ge=1, le=1000)
    useSeeding: bool = True
    useRepair: bool = True
    useLocalSearch: bool = True
    maxSeconds: float = Field(120, gt=0, le=1800)
    instance: dict | None = None


@app.get("/api/health")
def health():
    return {"ok": True}


class TimetableRequest(BaseModel):
    instance: dict
    solution: dict


class LeaveRequest(BaseModel):
    facultyId: str
    slots: list[int] = Field(min_length=1, max_length=168)


class CancellationRequest(BaseModel):
    eventId: str
    reason: str = Field(default='Cancelled lecture', max_length=500)


class RepairRequest(TimetableRequest):
    leaves: list[LeaveRequest] = Field(default_factory=list, max_length=1000)
    cancellations: list[CancellationRequest] = Field(default_factory=list, max_length=1000)


@app.post('/api/timetable/audit')
def audit_timetable(req: TimetableRequest):
    try:
        return audit(req.instance, req.solution)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise HTTPException(422, f'Invalid timetable input: {exc}') from exc


@app.post('/api/timetable/repair')
def repair_week(req: RepairRequest):
    try:
        return repair_timetable(req.instance, req.solution,
                                [x.model_dump() for x in req.leaves],
                                [x.model_dump() for x in req.cancellations])
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        raise HTTPException(422, f'Invalid timetable input: {exc}') from exc


@app.get("/api/scenarios")
def scenarios():
    out = [{"id": "demo", "label": "Demo (SY Computer, 2 divisions)"}]
    out += [{"id": k, "label": v["label"]} for k, v in SCENARIOS.items()]
    for s in out:
        inst = generate(s["id"], 1)
        s.update(events=len(inst.events), groups=len(inst.groups), rooms=len(inst.rooms), faculty=len(inst.faculty))
    return out


def _work(job_id: str, params: RunParams):
    job = _jobs[job_id]

    def progress(entry: dict):
        job["progress"] = {
            "generation": entry["generation"],
            "total": params.generations,
            "archiveSize": entry["archive_size"],
            "feasibleFraction": entry["feasible_fraction"],
            "seconds": entry["seconds"],
        }

    try:
        result = run(params, progress)
        for solution in result['solutions']:
            if not audit(result['instance'], solution)['valid']:
                raise RuntimeError('The optimiser returned a timetable that failed independent constraint validation')
        job["result"] = result
        job["status"] = "done"
    except Exception as e:  # report to the client instead of failing silently
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    job["finished"] = time.time()


@app.post("/api/runs")
def start_run(req: RunRequest):
    if req.instance is not None:
        try:
            custom = checked_instance(req.instance)
            if any(not o.eligible_faculty for o in custom.offerings):
                raise ValueError('Every offering needs at least one eligible teacher for re-optimisation; use repair to keep impossible lectures pending')
            if any(f.max_weekly == 0 or f.max_daily == 0 for f in custom.faculty):
                # A zero-load teacher may stay in the instance but must not be sampled.
                blocked = {f.id for f in custom.faculty if f.max_weekly == 0 or f.max_daily == 0}
                for o in custom.offerings:
                    o.eligible_faculty = [f for f in o.eligible_faculty if f not in blocked]
                    if not o.eligible_faculty:
                        raise ValueError('No teacher with positive load limits for an offering; use repair to keep lectures pending')
            req.instance = custom.to_dict()
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise HTTPException(422, f'Invalid constraints: {exc}') from exc
    if req.scenario not in ("demo", *SCENARIOS):
        raise HTTPException(400, f"Unknown scenario '{req.scenario}'")
    params = RunParams(
        scenario=req.scenario,
        instance_seed=req.instanceSeed,
        seed=req.seed,
        pop_size=req.popSize,
        generations=req.generations,
        use_seeding=req.useSeeding,
        use_repair=req.useRepair,
        use_local_search=req.useLocalSearch,
        max_seconds=req.maxSeconds,
        instance_override=req.instance,
    )
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        if len(_jobs) >= MAX_JOBS_KEPT:  # forget the oldest finished jobs
            for k in sorted((k for k, j in _jobs.items() if j["status"] != "running"), key=lambda k: _jobs[k]["started"])[
                : len(_jobs) - MAX_JOBS_KEPT + 1
            ]:
                del _jobs[k]
        _jobs[job_id] = {"status": "running", "started": time.time(), "progress": {"generation": 0, "total": req.generations}}
    _executor.submit(_work, job_id, params)
    return {"runId": job_id}


@app.get("/api/runs/{job_id}")
def get_run(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Run not found")
    out = {"status": job["status"], "progress": job.get("progress")}
    if job["status"] == "done":
        out["result"] = job["result"]
    if job["status"] == "error":
        out["error"] = job["error"]
    return out
