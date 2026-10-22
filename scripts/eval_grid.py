"""Run Harbor baseline and mage against one model server per manifest cell.

eval-host still owns the allocation, the tunnel, and the smoke gates.
This runner starts it with --setup-only, then starts Harbor itself so
slot count and task stage stay out of that script.

parallel on a cell is both llama.cpp -np and Harbor --n-concurrent.
probe grades one task per condition. confirm grades confirm_tasks and
runs only when the operator passes --stage confirm.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LIB = Path(__file__).resolve().parent / "lib"
sys.path.insert(0, str(LIB))
import mage_scholar  # noqa: E402

from scripts.harbor.cache_layout import (  # noqa: E402
    CACHE_IN_CONTAINER,
    cache_ready,
    default_cache_dir,
    mount_spec,
)

KNOWN_DATASETS = {"swebenchpro"}
CELL_KEYS = {"profile", "context", "parallel"}
CONDITIONS = ("baseline", "mage")
GIB = 1024**3


class GridError(Exception):
    pass


@dataclass(frozen=True)
class Cell:
    profile: str
    context: int
    parallel: int


@dataclass(frozen=True)
class Allocation:
    account: str
    partition: str
    gpus: int
    cpus: int
    mem: str
    time: str
    jump: str


@dataclass(frozen=True)
class Manifest:
    slots_at_128k: int
    memory_stop_gib: float
    stages: tuple[str, ...]
    probe_tasks: int
    confirm_tasks: int
    datasets: tuple[str, ...]
    cells: tuple[Cell, ...]
    allocation: Allocation


@dataclass(frozen=True)
class PlannedJob:
    dataset: str
    condition: str
    argv: list[str]


@dataclass(frozen=True)
class PlannedCell:
    index: int
    cell: Cell
    alias: str
    eval_host: list[str]
    jobs: tuple[PlannedJob, ...]


class ServerHandle(Protocol):
    def readline(self, timeout: float) -> str | None: ...

    def exited(self) -> int | None: ...

    def stop(self) -> None: ...


class GridIO(Protocol):
    def start_server(self, argv: list[str]) -> ServerHandle: ...

    def memory_bytes(self, jump: str, model_ssh: str, job_id: str = "") -> int | None: ...

    def run_harbor(self, argv: list[str], env: dict[str, str]) -> int: ...


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GridError(f"{label} must be a positive integer.")
    return value


def _mem_gib(mem: str) -> int | None:
    if len(mem) < 2 or not mem[:-1].isdigit() or mem[-1] not in {"G", "M"}:
        return None
    amount = int(mem[:-1])
    if mem[-1] == "G":
        return amount
    return amount // 1024


def load_manifest(path: Path) -> Manifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GridError(f"Could not read manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise GridError("Manifest must be a JSON object.")
    cells_raw = raw.get("cells")
    if not isinstance(cells_raw, list) or not cells_raw:
        raise GridError("Manifest cells must be a non-empty list.")
    cells: list[Cell] = []
    for index, item in enumerate(cells_raw):
        if not isinstance(item, dict):
            raise GridError(f"Cell {index} must be an object.")
        extra = set(item) - CELL_KEYS
        if extra:
            raise GridError(
                f"Cell {index} has {', '.join(sorted(extra))}. "
                "parallel is the only slot count and is both -np and --n-concurrent."
            )
        missing = CELL_KEYS - set(item)
        if missing:
            raise GridError(f"Cell {index} is missing {', '.join(sorted(missing))}.")
        profile = item["profile"]
        if not isinstance(profile, str) or profile not in mage_scholar.PROFILES:
            raise GridError(f"Cell {index} profile is not a known profile: {profile!r}.")
        cells.append(
            Cell(
                profile=profile,
                context=_positive_int(item["context"], f"cell {index} context"),
                parallel=_positive_int(item["parallel"], f"cell {index} parallel"),
            )
        )
    datasets_raw = raw.get("datasets")
    if not isinstance(datasets_raw, list) or not datasets_raw:
        raise GridError("Manifest datasets must be a non-empty list.")
    datasets: list[str] = []
    for dataset in datasets_raw:
        if not isinstance(dataset, str) or not dataset:
            raise GridError("Each dataset id must be a non-empty string.")
        if dataset not in KNOWN_DATASETS:
            raise GridError(
                f"Unknown dataset {dataset!r}. The grid accepts {', '.join(sorted(KNOWN_DATASETS))}. "
                "Add an id only after harbor datasets list shows it."
            )
        datasets.append(dataset)
    stages_raw = raw.get("stages")
    if stages_raw != ["probe", "confirm"]:
        raise GridError('Manifest stages must be ["probe", "confirm"].')
    if "conditions" in raw and raw["conditions"] != ["baseline", "mage"]:
        raise GridError("conditions must be baseline then mage. They share one server.")
    slots = _positive_int(raw.get("slots_at_128k"), "slots_at_128k")
    wide = [cell for cell in cells if cell.context == 131072]
    if not wide or any(cell.parallel != slots for cell in wide):
        raise GridError("slots_at_128k must equal parallel on every 131072-context cell.")
    stop = raw.get("memory_stop_gib")
    if isinstance(stop, bool) or not isinstance(stop, (int, float)) or stop <= 0:
        raise GridError("memory_stop_gib must be a positive number.")
    allocation_raw = raw.get("allocation")
    if not isinstance(allocation_raw, dict):
        raise GridError("Manifest allocation must be an object.")
    try:
        allocation = Allocation(
            account=str(allocation_raw["account"]),
            partition=str(allocation_raw["partition"]),
            gpus=_positive_int(allocation_raw["gpus"], "allocation gpus"),
            cpus=_positive_int(allocation_raw["cpus"], "allocation cpus"),
            mem=str(allocation_raw["mem"]),
            time=str(allocation_raw["time"]),
            jump=str(allocation_raw["jump"]),
        )
    except KeyError as exc:
        raise GridError(f"Manifest allocation is missing {exc.args[0]}.") from exc
    if not allocation.mem or not allocation.time or not allocation.jump:
        raise GridError("Manifest allocation needs mem, time, and jump.")
    request_gib = _mem_gib(allocation.mem)
    if request_gib is not None and float(stop) >= request_gib:
        raise GridError(
            f"memory_stop_gib ({stop}) must be below the {allocation.mem} request "
            "so a full cgroup can stop the cell before the job is killed."
        )
    return Manifest(
        slots_at_128k=slots,
        memory_stop_gib=float(stop),
        stages=("probe", "confirm"),
        probe_tasks=_positive_int(raw.get("probe_tasks"), "probe_tasks"),
        confirm_tasks=_positive_int(raw.get("confirm_tasks"), "confirm_tasks"),
        datasets=tuple(datasets),
        cells=tuple(cells),
        allocation=allocation,
    )


def tasks_for(manifest: Manifest, stage: str) -> int:
    if stage == "probe":
        return manifest.probe_tasks
    if stage == "confirm":
        return manifest.confirm_tasks
    raise GridError(f"Unknown stage {stage!r}. Use probe or confirm.")


def profile_alias(profile: str) -> str:
    return str(mage_scholar.PROFILES[profile]["model_alias"])


def eval_host_argv(repo: Path, cell: Cell, allocation: Allocation) -> list[str]:
    return [
        "bash",
        str(repo / "scripts" / "eval-host"),
        "--setup-only",
        "--model-profile",
        cell.profile,
        "--context",
        str(cell.context),
        "--parallel",
        str(cell.parallel),
        "--jump",
        allocation.jump,
        "--account",
        allocation.account,
        "--partition",
        allocation.partition,
        "--gpus",
        str(allocation.gpus),
        "--cpus",
        str(allocation.cpus),
        "--mem",
        allocation.mem,
        "--time",
        allocation.time,
    ]


def harbor_argv(
    *,
    cell: Cell,
    dataset: str,
    condition: str,
    alias: str,
    base_url: str,
    n_tasks: int,
    jobs_dir: Path,
    stage: str,
    skills: Path,
    cache: Path | None,
    resolved: dict[str, Any],
) -> list[str]:
    config = mage_scholar.render_opencode(base_url, resolved)
    config_line = json.dumps(config, separators=(",", ":"))
    job = f"mage-grid-{stage}-{dataset}-{condition}-{alias}-c{cell.context}-p{cell.parallel}"
    if cache is not None and cache_ready(cache):
        agent_args = [
            "--agent",
            "scripts.harbor.opencode_cached:OpenCodeCached",
            "--mounts",
            json.dumps([mount_spec(cache)], separators=(",", ":")),
        ]
    else:
        agent_args = ["--agent", "opencode"]
    argv = [
        "harbor",
        "run",
        "--yes",
        *agent_args,
        "--dataset",
        dataset,
        "--model",
        f"scholar/{alias}",
        "--n-tasks",
        str(n_tasks),
        "--n-concurrent",
        str(cell.parallel),
        "--job-name",
        job,
        "--jobs-dir",
        str(jobs_dir),
        "--ae",
        f"OPENAI_BASE_URL={base_url}",
        "--ae",
        "OPENAI_API_KEY=local",
        "--ae",
        f"OPENCODE_CONFIG_CONTENT={config_line}",
    ]
    if condition == "mage":
        argv.extend(["--skill", str(skills)])
    return argv


def plan(
    manifest: Manifest,
    stage: str,
    repo: Path,
    allocation: Allocation,
    cache: Path | None,
    jobs_dir: Path,
) -> list[PlannedCell]:
    n_tasks = tasks_for(manifest, stage)
    skills = repo / ".agents" / "skills"
    planned: list[PlannedCell] = []
    for index, cell in enumerate(manifest.cells):
        alias = profile_alias(cell.profile)
        base_url = "http://host.docker.internal:18080/v1"
        resolved = {
            "model_alias": alias,
            "context": cell.context,
            "output_limit": mage_scholar.PROFILES[cell.profile]["output_limit"],
        }
        jobs = tuple(
            PlannedJob(
                dataset=dataset,
                condition=condition,
                argv=harbor_argv(
                    cell=cell,
                    dataset=dataset,
                    condition=condition,
                    alias=alias,
                    base_url=base_url,
                    n_tasks=n_tasks,
                    jobs_dir=jobs_dir,
                    stage=stage,
                    skills=skills,
                    cache=cache,
                    resolved=resolved,
                ),
            )
            for dataset in manifest.datasets
            for condition in CONDITIONS
        )
        planned.append(
            PlannedCell(
                index=index,
                cell=cell,
                alias=alias,
                eval_host=eval_host_argv(repo, cell, allocation),
                jobs=jobs,
            )
        )
    return planned


def print_plan(cells: list[PlannedCell], cache_is_ready: bool) -> None:
    if cache_is_ready:
        print(f"OpenCode cache mounted at {CACHE_IN_CONTAINER}. Trials skip nvm and npm when the pin matches.")
    else:
        print("OpenCode cache is absent. Each trial will install opencode. Run scripts/prefetch-opencode first.")
    for planned in cells:
        cell = planned.cell
        print(
            f"Cell {planned.index}: {cell.profile} context {cell.context} "
            f"parallel {cell.parallel} alias {planned.alias}"
        )
        print("  eval-host " + shlex.join(planned.eval_host))
        for job in planned.jobs:
            print(f"  harbor {job.dataset} {job.condition}")
            print("    " + shlex.join(job.argv))
    print("Conditions share the server. Jobs run one after another at full parallel.")
    print("Dry run: no sbatch, ssh, docker, or Harbor job was started.")


def parse_slot_payload(payload: Any) -> tuple[int, int] | None:
    """Return (slot_count, busy_count) from a llama.cpp /slots body."""
    if isinstance(payload, dict):
        slots = payload.get("slots")
        if isinstance(slots, list):
            payload = slots
        else:
            return None
    if not isinstance(payload, list):
        return None
    busy = 0
    counted = 0
    for slot in payload:
        if not isinstance(slot, dict):
            continue
        counted += 1
        if slot.get("is_processing") is True:
            busy += 1
    return counted, busy


def summarize_slot_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Occupancy over the Harbor window. Missing samples stay unknown."""
    if not samples:
        return {
            "samples": 0,
            "slot_count": None,
            "mean_busy_slots": None,
            "max_busy_slots": None,
            "mean_occupancy": None,
            "fraction_all_busy": None,
        }
    counts = [int(sample["n_slots"]) for sample in samples]
    busy = [int(sample["n_busy"]) for sample in samples]
    occupancy = [b / n if n else 0.0 for b, n in zip(busy, counts)]
    all_busy = sum(1 for b, n in zip(busy, counts) if n and b >= n)
    return {
        "samples": len(samples),
        "slot_count": counts[-1],
        "mean_busy_slots": sum(busy) / len(busy),
        "max_busy_slots": max(busy),
        "mean_occupancy": sum(occupancy) / len(occupancy),
        "fraction_all_busy": all_busy / len(samples),
    }


class SlotSampler:
    """Poll the local tunnel's /slots while Harbor is running."""

    def __init__(self, slots_url: str, interval: float = 5.0) -> None:
        self.slots_url = slots_url
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="slot-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 2)
        with self._lock:
            return list(self.samples)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def _sample(self) -> None:
        request = urllib.request.Request(self.slots_url)
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return
        parsed = parse_slot_payload(payload)
        if parsed is None:
            return
        n_slots, n_busy = parsed
        sample = {
            "t": time.time(),
            "n_slots": n_slots,
            "n_busy": n_busy,
        }
        with self._lock:
            self.samples.append(sample)


def memory_decision(current: int | None, parallel: int, stop_gib: float) -> tuple[str, str]:
    if current is None:
        if parallel > 1:
            return (
                "stop",
                "cgroup memory was not readable and parallel is above 1. "
                "The cell stops so a 100G job is not filled by an unmeasured KV cache.",
            )
        return "run", "cgroup memory was not readable; parallel is 1."
    limit = int(stop_gib * GIB)
    gib = current / GIB
    if current >= limit:
        return (
            "stop",
            f"cgroup memory is {gib:.1f} GiB, at or above the {stop_gib:g} GiB stop. "
            "Lower parallel and run this cell again. There is no automatic retry.",
        )
    return "run", f"cgroup memory is {gib:.1f} GiB, under the {stop_gib:g} GiB stop."


# The step cgroup is only the srun/ssh process. The job total is the
# directory directly under slurmstepd.scope.
CGROUP_READ = (
    "cg=$(awk -F: '$1==0 {print $3}' /proc/self/cgroup); "
    'd="/sys/fs/cgroup${cg}"; '
    'while [ "$(basename "$(dirname "$d")")" != slurmstepd.scope ] && [ "$d" != /sys/fs/cgroup ]; do '
    'd=$(dirname "$d"); done; '
    'cat "$d/memory.current"'
)


def memory_srun_argv(jump: str, job_id: str) -> list[str]:
    if not job_id.isdigit():
        raise ValueError(f"job id must be digits, got {job_id!r}")
    remote = f"srun --jobid={job_id} --overlap --ntasks=1 bash -lc {shlex.quote(CGROUP_READ)}"
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if jump:
        argv.append(jump)
    argv.append(remote)
    return argv


def memory_ssh_argv(jump: str, model_ssh: str) -> list[str]:
    remote = f"bash -lc {shlex.quote(CGROUP_READ)}"
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if jump:
        argv.extend(["-J", jump])
    argv.extend([model_ssh, remote])
    return argv


def parse_memory_bytes(stdout: str) -> int | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.isdigit():
            return int(text)
    return None


def parse_tunnel(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def harbor_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo) if not previous else str(repo) + os.pathsep + previous
    return env


def wait_until_ready(server: ServerHandle, timeout: float) -> tuple[str, str]:
    run_dir = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        line = server.readline(min(5.0, remaining))
        if line is None:
            continue
        if line == "":
            raise GridError(f"eval-host exited ({server.exited()}) before the model was ready.")
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
        if line.startswith("Run directory: "):
            run_dir = line.split(":", 1)[1].strip()
        if line.startswith("Container base URL: "):
            base_url = line.removeprefix("Container base URL: ").strip()
            if not run_dir:
                raise GridError("Container URL arrived before the run directory.")
            return run_dir, base_url
    raise GridError(f"Timed out after {timeout:g}s waiting for the model server.")


class SubprocessServer:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc

    def readline(self, timeout: float) -> str | None:
        if self.proc.stdout is None:
            return ""
        ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not ready:
            return None
        return self.proc.stdout.readline()

    def exited(self) -> int | None:
        return self.proc.poll()

    def stop(self) -> None:
        if self.proc.poll() is not None:
            return
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


class LiveIO:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def start_server(self, argv: list[str]) -> ServerHandle:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        return SubprocessServer(proc)

    def memory_bytes(self, jump: str, model_ssh: str, job_id: str = "") -> int | None:
        attempts = [("node-ssh", memory_ssh_argv(jump, model_ssh))]
        if job_id.isdigit():
            attempts.append(("srun", memory_srun_argv(jump, job_id)))
        for name, argv in attempts:
            try:
                completed = subprocess.run(argv, capture_output=True, text=True, timeout=40)
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"Memory read via {name} failed: {exc}")
                continue
            parsed = parse_memory_bytes(completed.stdout)
            if completed.returncode == 0 and parsed is not None:
                return parsed
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit {completed.returncode}"
            print(f"Memory read via {name} failed: {tail}")
        return None

    def run_harbor(self, argv: list[str], env: dict[str, str]) -> int:
        completed = subprocess.run(argv, env=env, cwd=self.repo)
        return completed.returncode


def _write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_cell(
    *,
    io: GridIO,
    planned: PlannedCell,
    manifest: Manifest,
    allocation: Allocation,
    stage: str,
    repo: Path,
    cache: Path | None,
    grid_dir: Path,
    startup_timeout: float,
) -> str:
    """Return 'ok', 'memory', or 'harbor'."""
    cell = planned.cell
    started = time.monotonic()
    summary: dict[str, Any] = {
        "profile": cell.profile,
        "context": cell.context,
        "parallel": cell.parallel,
        "stage": stage,
        "eval_host": planned.eval_host,
        "jobs": [],
        "timing": {"started_unix": time.time()},
    }
    summary_path = grid_dir / f"cell-{planned.index}.json"
    server = io.start_server(planned.eval_host)
    status = "ok"
    sampler: SlotSampler | None = None
    try:
        run_dir, base_url = wait_until_ready(server, startup_timeout)
        summary["run_dir"] = run_dir
        summary["base_url"] = base_url
        summary["timing"]["server_ready_sec"] = round(time.monotonic() - started, 3)
        print(f"Timing: server ready in {summary['timing']['server_ready_sec']:.1f}s")
        tunnel = parse_tunnel((Path(run_dir) / "tunnel.txt").read_text(encoding="utf-8"))
        model_ssh = tunnel.get("model_ssh", "")
        jump = tunnel.get("jump", allocation.jump)
        if not model_ssh:
            raise GridError(f"tunnel.txt in {run_dir} has no model_ssh.")
        job_id = ""
        state_path = Path(run_dir) / "state.json"
        if state_path.is_file():
            try:
                job_id = str(json.loads(state_path.read_text(encoding="utf-8")).get("job_id") or "")
            except json.JSONDecodeError:
                job_id = ""
        current = io.memory_bytes(jump, model_ssh, job_id)
        action, reason = memory_decision(current, cell.parallel, manifest.memory_stop_gib)
        summary["memory_bytes"] = current
        summary["memory_action"] = action
        summary["memory_reason"] = reason
        summary["timing"]["memory_check_sec"] = round(time.monotonic() - started, 3)
        print(f"Cell {planned.index}: {reason}")
        if action == "stop":
            status = "memory"
            return status
        local_port = tunnel.get("local_port", "")
        if local_port.isdigit():
            sampler = SlotSampler(f"http://127.0.0.1:{local_port}/slots")
            sampler.start()
        resolved = json.loads((Path(run_dir) / "resolved-config.json").read_text(encoding="utf-8"))
        alias = str(resolved["model_alias"])
        skills = repo / ".agents" / "skills"
        n_tasks = tasks_for(manifest, stage)
        env = harbor_env(repo)
        for dataset in manifest.datasets:
            for condition in CONDITIONS:
                argv = harbor_argv(
                    cell=cell,
                    dataset=dataset,
                    condition=condition,
                    alias=alias,
                    base_url=base_url,
                    n_tasks=n_tasks,
                    jobs_dir=grid_dir / "harbor",
                    stage=stage,
                    skills=skills,
                    cache=cache,
                    resolved=resolved,
                )
                print(f"Harbor {dataset} {condition} n-tasks {n_tasks} n-concurrent {cell.parallel}")
                job_started = time.monotonic()
                code = io.run_harbor(argv, env)
                wall = round(time.monotonic() - job_started, 3)
                print(f"Timing: harbor {dataset} {condition} {wall:.1f}s exit {code}")
                summary["jobs"].append(
                    {
                        "dataset": dataset,
                        "condition": condition,
                        "exit_code": code,
                        "wall_sec": wall,
                        "n_tasks": n_tasks,
                        "n_concurrent": cell.parallel,
                    }
                )
                if code != 0:
                    status = "harbor"
        return status
    finally:
        if sampler is not None:
            samples = sampler.stop()
            slots_path = grid_dir / f"cell-{planned.index}-slots.jsonl"
            slots_path.write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples),
                encoding="utf-8",
            )
            summary["slots"] = summarize_slot_samples(samples)
            summary["slots_file"] = str(slots_path)
        summary["timing"]["cell_wall_sec"] = round(time.monotonic() - started, 3)
        try:
            server.stop()
        finally:
            _write_summary(summary_path, summary)


def execute(
    *,
    manifest: Manifest,
    stage: str,
    repo: Path,
    allocation: Allocation,
    cache: Path | None,
    state_dir: Path,
    io: GridIO,
    startup_timeout: float,
    only: str | None,
) -> int:
    skills = repo / ".agents" / "skills"
    if not skills.is_dir():
        print(f"Missing skills directory: {skills}", file=sys.stderr)
        return 2
    selected = plan(manifest, stage, repo, allocation, cache, state_dir / "harbor")
    if only is not None:
        selected = _filter_cells(selected, only)
        if not selected:
            print(f"No cell matches {only!r}.", file=sys.stderr)
            return 2
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    grid_dir = state_dir / f"grid-{stamp}"
    grid_dir.mkdir(parents=True, exist_ok=True)
    print(f"Grid directory: {grid_dir}")
    worst = 0
    for planned in selected:
        cell = planned.cell
        print(
            f"Starting cell {planned.index}: {cell.profile} "
            f"context {cell.context} parallel {cell.parallel}"
        )
        try:
            status = run_cell(
                io=io,
                planned=planned,
                manifest=manifest,
                allocation=allocation,
                stage=stage,
                repo=repo,
                cache=cache,
                grid_dir=grid_dir,
                startup_timeout=startup_timeout,
            )
        except (GridError, OSError, json.JSONDecodeError) as exc:
            print(f"Cell {planned.index} failed: {exc}", file=sys.stderr)
            worst = max(worst, 1)
            continue
        if status == "memory":
            worst = max(worst, 3)
        elif status == "harbor":
            worst = max(worst, 1)
    return worst


def _filter_cells(cells: list[PlannedCell], only: str) -> list[PlannedCell]:
    if only.isdigit():
        index = int(only)
        return [cell for cell in cells if cell.index == index]
    if ":" not in only:
        raise GridError("--only expects an index or profile:context.")
    profile, _, context_text = only.partition(":")
    if not context_text.isdigit():
        raise GridError("--only context must be an integer.")
    context = int(context_text)
    return [cell for cell in cells if cell.cell.profile == profile and cell.cell.context == context]


def _apply_overrides(manifest: Manifest, args: argparse.Namespace) -> Allocation:
    allocation = manifest.allocation
    return Allocation(
        account=args.account or allocation.account,
        partition=args.partition or allocation.partition,
        gpus=args.gpus if args.gpus is not None else allocation.gpus,
        cpus=args.cpus if args.cpus is not None else allocation.cpus,
        mem=args.mem or allocation.mem,
        time=args.time or allocation.time,
        jump=args.jump or allocation.jump,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Grade one manifest cell at a time. One model server, then Harbor "
            "baseline and mage. Default stage is probe (1 task). "
            "confirm runs only with --stage confirm."
        )
    )
    parser.add_argument("--manifest", type=Path, default=ROOT / "scripts" / "eval-grid.json")
    parser.add_argument("--stage", choices=("probe", "confirm"), default="probe")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default=None, help="Cell index or profile:context.")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--startup-timeout", type=float, default=1800)
    parser.add_argument("--jump", default=None)
    parser.add_argument("--account", default=None)
    parser.add_argument("--partition", default=None)
    parser.add_argument("--gpus", type=int, default=None)
    parser.add_argument("--cpus", type=int, default=None)
    parser.add_argument("--mem", default=None)
    parser.add_argument("--time", default=None)
    parser.add_argument("--memory-stop-gib", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except GridError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.memory_stop_gib is not None:
        manifest = Manifest(
            slots_at_128k=manifest.slots_at_128k,
            memory_stop_gib=args.memory_stop_gib,
            stages=manifest.stages,
            probe_tasks=manifest.probe_tasks,
            confirm_tasks=manifest.confirm_tasks,
            datasets=manifest.datasets,
            cells=manifest.cells,
            allocation=manifest.allocation,
        )
    allocation = _apply_overrides(manifest, args)
    request_gib = _mem_gib(allocation.mem)
    if request_gib is not None and manifest.memory_stop_gib >= request_gib:
        print(
            f"memory_stop_gib ({manifest.memory_stop_gib:g}) must be below the {allocation.mem} request.",
            file=sys.stderr,
        )
        return 2
    cache = args.cache if args.cache is not None else default_cache_dir()
    ready = cache_ready(cache)
    if args.dry_run:
        try:
            cells = plan(manifest, args.stage, ROOT, allocation, cache, Path("<grid>/harbor"))
            cells = _filter_cells(cells, args.only) if args.only else cells
        except GridError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.only and not cells:
            print(f"No cell matches {args.only!r}.", file=sys.stderr)
            return 2
        print_plan(cells, ready)
        return 0
    state_parent = args.state_dir
    if state_parent is None:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        state_parent = Path(base) / "mage-eval" / "grid"
    try:
        return execute(
            manifest=manifest,
            stage=args.stage,
            repo=ROOT,
            allocation=allocation,
            cache=cache if ready else None,
            state_dir=state_parent,
            io=LiveIO(ROOT),
            startup_timeout=args.startup_timeout,
            only=args.only,
        )
    except GridError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
