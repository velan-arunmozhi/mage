import asyncio
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import scripts.eval_grid as grid
from scripts.harbor import cache_layout
import mage_scholar

MANIFEST = ROOT / "scripts" / "eval-grid.json"
GIB = 1024**3


def flag(argv, name):
    return argv[argv.index(name) + 1]


def n_tasks_in(output):
    found = []
    for line in output.splitlines():
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue
        if "--n-tasks" in tokens:
            found.append(tokens[tokens.index("--n-tasks") + 1])
    return found


def harbor_site_packages() -> Path | None:
    candidates = []
    found = shutil.which("harbor")
    if found:
        candidates.append(Path(found))
    candidates.append(Path.home() / ".local" / "bin" / "harbor")
    for harbor in candidates:
        if not harbor.is_file():
            continue
        shebang = harbor.read_text(encoding="utf-8").splitlines()[0]
        if not shebang.startswith("#!"):
            continue
        python = Path(shebang[2:].strip().split()[0]).resolve()
        matches = sorted((python.parent.parent / "lib").glob("python*/site-packages"))
        if matches:
            return matches[0]
    uv = Path.home() / ".local" / "share" / "uv" / "tools" / "harbor" / "lib"
    matches = sorted(uv.glob("python*/site-packages"))
    return matches[0] if matches else None


def ready_cache(root: Path) -> Path:
    cache = root / "cache"
    node = cache / "node" / "bin" / "node"
    opencode = cache / "prefix" / "bin" / "opencode"
    node.parent.mkdir(parents=True)
    opencode.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    opencode.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(node.stat().st_mode | stat.S_IXUSR)
    opencode.chmod(opencode.stat().st_mode | stat.S_IXUSR)
    (cache / "VERSION").write_text(cache_layout.OPENCODE_VERSION + "\n", encoding="utf-8")
    return cache


class FakeServer:
    def __init__(self, lines):
        self.lines = list(lines)
        self.stops = 0
        self.code = None

    def readline(self, timeout):
        if self.lines:
            return self.lines.pop(0)
        self.code = 1
        return ""

    def exited(self):
        return self.code

    def stop(self):
        self.stops += 1
        self.code = 0


class FakeIO:
    def __init__(self, lines, memory):
        self.lines = list(lines)
        self.memory = memory
        self.started = []
        self.harbor = []
        self.servers = []
        self.memory_calls = []

    def start_server(self, argv):
        server = FakeServer(self.lines)
        self.servers.append(server)
        self.started.append(list(argv))
        return server

    def memory_bytes(self, jump, model_ssh, job_id=""):
        self.memory_calls.append((jump, model_ssh, job_id))
        return self.memory

    def run_harbor(self, argv, env):
        self.harbor.append(list(argv))
        self.env = env
        return 0


class Result:
    def __init__(self, code, out=""):
        self.return_code = code
        self.stdout = out
        self.stderr = ""


class FakeEnv:
    def __init__(self, probe_code, probe_out):
        self.probe_code = probe_code
        self.probe_out = probe_out
        self.commands = []

    async def exec(self, command, user=None, env=None, cwd=None, timeout_sec=None):
        self.commands.append(command)
        if "binary" in command:
            return Result(self.probe_code, self.probe_out)
        return Result(0, "")


def write_run(root: Path) -> Path:
    run = root / "run"
    run.mkdir()
    (run / "tunnel.txt").write_text(
        "model_ssh=billin19@scholar-k060.rcac.purdue.edu\njump=scholar\nlocal_port=18080\nremote_port=8080\n",
        encoding="utf-8",
    )
    (run / "resolved-config.json").write_text(
        json.dumps(
            {
                "model_alias": "qwen36-35b",
                "context": 131072,
                "output_limit": 8192,
                "parallel": 5,
            }
        ),
        encoding="utf-8",
    )
    return run


class SlotSampleTests(unittest.TestCase):
    def test_occupancy_uses_processing_slots_only(self):
        parsed = grid.parse_slot_payload(
            [
                {"id": 0, "is_processing": True},
                {"id": 1, "is_processing": False},
                {"id": 2, "is_processing": True},
                {"id": 3, "is_processing": False},
            ]
        )
        self.assertEqual(parsed, (4, 2))
        summary = grid.summarize_slot_samples(
            [
                {"t": 1, "n_slots": 4, "n_busy": 1},
                {"t": 2, "n_slots": 4, "n_busy": 4},
                {"t": 3, "n_slots": 4, "n_busy": 0},
            ]
        )
        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["max_busy_slots"], 4)
        self.assertAlmostEqual(summary["mean_busy_slots"], 5 / 3)
        self.assertAlmostEqual(summary["mean_occupancy"], (0.25 + 1 + 0) / 3)
        self.assertAlmostEqual(summary["fraction_all_busy"], 1 / 3)
        self.assertIsNone(grid.summarize_slot_samples([])["mean_occupancy"])


class ManifestTests(unittest.TestCase):
    def test_shipped_manifest_matches_the_cell_plan(self):
        manifest = grid.load_manifest(MANIFEST)
        self.assertEqual(manifest.slots_at_128k, 5)
        self.assertEqual(manifest.memory_stop_gib, 90)
        self.assertEqual(manifest.probe_tasks, 1)
        self.assertEqual(manifest.confirm_tasks, 12)
        self.assertEqual(manifest.datasets, ("swebenchpro",))
        self.assertEqual(
            [(cell.profile, cell.context, cell.parallel) for cell in manifest.cells],
            [
                ("qwen36-35b", 131072, 5),
                ("qwen36-35b", 32768, 8),
                ("smoke-4b", 16384, 8),
            ],
        )

    def test_unknown_dataset_fails_before_a_cell_can_start(self):
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        raw["datasets"] = ["featurebench"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(grid.GridError) as caught:
                grid.load_manifest(path)
        self.assertIn("featurebench", str(caught.exception))
        self.assertIn("swebenchpro", str(caught.exception))

    def test_split_slot_counts_are_rejected(self):
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        raw["cells"][0]["n_concurrent"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(grid.GridError) as caught:
                grid.load_manifest(path)
        self.assertIn("n_concurrent", str(caught.exception))
        self.assertIn("parallel", str(caught.exception))

    def test_memory_stop_must_sit_below_the_request(self):
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        raw["memory_stop_gib"] = 100
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(grid.GridError):
                grid.load_manifest(path)


class PlanTests(unittest.TestCase):
    def test_probe_is_the_default_and_shares_one_server(self):
        self.assertEqual(grid.parse_args([]).stage, "probe")
        manifest = grid.load_manifest(MANIFEST)
        planned = grid.plan(
            manifest,
            "probe",
            ROOT,
            manifest.allocation,
            None,
            Path("<grid>/harbor"),
        )
        self.assertEqual(len(planned), 3)
        self.assertEqual(len(planned[0].jobs), 2)
        self.assertEqual([job.condition for job in planned[0].jobs], ["baseline", "mage"])
        host = planned[0].eval_host
        self.assertIn("--setup-only", host)
        self.assertEqual(flag(host, "--parallel"), "5")
        self.assertEqual(flag(host, "--context"), "131072")
        for job in planned[0].jobs:
            self.assertEqual(flag(job.argv, "--n-concurrent"), "5")
            self.assertEqual(flag(job.argv, "--n-tasks"), "1")
            self.assertEqual(flag(job.argv, "--agent"), "opencode")
            self.assertEqual(flag(job.argv, "--dataset"), "swebenchpro")
        self.assertIn("--skill", planned[0].jobs[1].argv)
        self.assertNotIn("--skill", planned[0].jobs[0].argv)
        parallels = [flag(cell.eval_host, "--parallel") for cell in planned]
        concurrents = [flag(job.argv, "--n-concurrent") for cell in planned for job in cell.jobs]
        self.assertEqual(parallels, ["5", "8", "8"])
        self.assertEqual(concurrents, ["5", "5", "8", "8", "8", "8"])

    def test_confirm_uses_twelve_tasks_only_when_asked(self):
        self.assertEqual(grid.parse_args(["--stage", "confirm"]).stage, "confirm")
        manifest = grid.load_manifest(MANIFEST)
        planned = grid.plan(
            manifest,
            "confirm",
            ROOT,
            manifest.allocation,
            None,
            Path("<grid>/harbor"),
        )
        tasks = [flag(job.argv, "--n-tasks") for cell in planned for job in cell.jobs]
        self.assertEqual(set(tasks), {"12"})

    def test_ready_cache_selects_the_cached_agent(self):
        manifest = grid.load_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            cache = ready_cache(Path(tmp))
            planned = grid.plan(
                manifest,
                "probe",
                ROOT,
                manifest.allocation,
                cache,
                Path("<grid>/harbor"),
            )
        argv = planned[0].jobs[0].argv
        self.assertEqual(flag(argv, "--agent"), "scripts.harbor.opencode_cached:OpenCodeCached")
        mounts = json.loads(flag(argv, "--mounts"))
        self.assertEqual(mounts[0]["target"], "/opt/mage-opencode")
        self.assertEqual(mounts[0]["source"], str(cache))
        self.assertTrue(mounts[0]["read_only"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_the_plan_and_does_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--dry-run", "--cache", tmp]

            def fail(*args, **kwargs):
                raise AssertionError(f"dry-run launched a process: {args!r}")

            with mock.patch("scripts.eval_grid.subprocess.Popen", fail), mock.patch(
                "scripts.eval_grid.subprocess.run", fail
            ):
                code = grid.main(argv)
        self.assertEqual(code, 0)

    def test_wrapper_dry_run_stays_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = subprocess.run(
                ["bash", str(ROOT / "scripts" / "eval-grid"), "--dry-run", "--cache", tmp],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            confirm = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "eval-grid"),
                    "--stage",
                    "confirm",
                    "--dry-run",
                    "--cache",
                    tmp,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("Dry run: no sbatch, ssh, docker, or Harbor job was started.", probe.stdout)
        self.assertEqual(probe.stdout.count("--setup-only"), 3)
        self.assertEqual(n_tasks_in(probe.stdout), ["1"] * 6)
        self.assertEqual(confirm.returncode, 0, confirm.stderr)
        self.assertEqual(n_tasks_in(confirm.stdout), ["12"] * 6)
        for script in ("eval-grid", "prefetch-opencode", "eval-host"):
            syntax = subprocess.run(
                ["bash", "-n", str(ROOT / "scripts" / script)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)


class ExecuteTests(unittest.TestCase):
    def test_high_memory_stops_every_cell_without_lowering_parallel(self):
        manifest = grid.load_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_run(root)
            lines = [
                f"Run directory: {run}\n",
                "Container base URL: http://host.docker.internal:18080/v1\n",
            ]
            io = FakeIO(lines, 95 * GIB)
            code = grid.execute(
                manifest=manifest,
                stage="probe",
                repo=ROOT,
                allocation=manifest.allocation,
                cache=None,
                state_dir=root / "state",
                io=io,
                startup_timeout=5,
                only=None,
            )
        self.assertEqual(code, 3)
        self.assertEqual(len(io.started), 3)
        self.assertEqual([flag(argv, "--parallel") for argv in io.started], ["5", "8", "8"])
        self.assertEqual(io.harbor, [])
        self.assertEqual(io.memory_calls[0][0], "scholar")
        self.assertIn("scholar-k060", io.memory_calls[0][1])
        self.assertTrue(all(server.stops == 1 for server in io.servers))

    def test_probe_runs_both_conditions_on_one_server(self):
        manifest = grid.load_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = write_run(root)
            cache = ready_cache(root)
            lines = [
                f"Run directory: {run}\n",
                "Container base URL: http://host.docker.internal:18080/v1\n",
            ]
            io = FakeIO(lines, 70 * GIB)
            code = grid.execute(
                manifest=manifest,
                stage="probe",
                repo=ROOT,
                allocation=manifest.allocation,
                cache=cache,
                state_dir=root / "state",
                io=io,
                startup_timeout=5,
                only="0",
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(io.started), 1)
        self.assertEqual(flag(io.started[0], "--parallel"), "5")
        self.assertEqual(len(io.harbor), 2)
        self.assertEqual([flag(argv, "--n-tasks") for argv in io.harbor], ["1", "1"])
        self.assertEqual([flag(argv, "--n-concurrent") for argv in io.harbor], ["5", "5"])
        self.assertEqual(
            [flag(argv, "--agent") for argv in io.harbor],
            ["scripts.harbor.opencode_cached:OpenCodeCached"] * 2,
        )
        self.assertNotIn("--skill", io.harbor[0])
        self.assertIn("--skill", io.harbor[1])
        self.assertIn(str(ROOT), io.env["PYTHONPATH"])
        self.assertEqual(io.servers[0].stops, 1)

    def test_unreadable_memory_stops_when_parallel_is_above_one(self):
        action, reason = grid.memory_decision(None, 5, 90)
        self.assertEqual(action, "stop")
        self.assertIn("parallel", reason)
        action, _reason = grid.memory_decision(None, 1, 90)
        self.assertEqual(action, "run")
        action, reason = grid.memory_decision(70 * GIB, 5, 90)
        self.assertEqual(action, "run")
        self.assertIn("70.0 GiB", reason)

    def test_server_exit_does_not_start_harbor(self):
        manifest = grid.load_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            io = FakeIO(["still starting\n"], None)
            code = grid.execute(
                manifest=manifest,
                stage="probe",
                repo=ROOT,
                allocation=manifest.allocation,
                cache=None,
                state_dir=root / "state",
                io=io,
                startup_timeout=5,
                only="qwen36-35b:131072",
            )
        self.assertEqual(code, 1)
        self.assertEqual(io.harbor, [])
        self.assertEqual(io.servers[0].stops, 1)


class EvalHostParallelTests(unittest.TestCase):
    def test_parallel_reaches_llama_server_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["MAGE_STATE_DIR"] = tmp
            proc = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "eval-host"),
                    "--dry-run",
                    "--model-profile",
                    "qwen36-35b",
                    "--context",
                    "131072",
                    "--parallel",
                    "5",
                    "--partition",
                    "spark-batch",
                    "--account",
                    "scholar",
                    "--gpus",
                    "1",
                    "--cpus",
                    "20",
                    "--mem",
                    "100G",
                    "--time",
                    "02:00:00",
                    "--condition",
                    "baseline",
                    "--dataset",
                    "swebenchpro",
                    "--n-tasks",
                    "1",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Dry run: no sbatch, ssh, docker, model download, or Harbor job was started.", proc.stdout)
        start = proc.stdout.index("{")
        end = proc.stdout.index("\nRun directory:")
        resolved = json.loads(proc.stdout[start:end])
        self.assertEqual(resolved["parallel"], 5)
        self.assertEqual(resolved["context"], 131072)
        argv = mage_scholar.server_argv(resolved, "llama-server")
        self.assertEqual(argv[argv.index("-np") + 1], "5")
        self.assertEqual(argv[argv.index("-c") + 1], "655360")


class CacheTests(unittest.TestCase):
    def test_version_match_requires_the_binary_and_the_pin_file(self):
        pinned = cache_layout.OPENCODE_VERSION
        good = f"binary\n{pinned}\npinned\n{pinned}\n"
        self.assertTrue(cache_layout.version_matches(good, pinned))
        self.assertFalse(cache_layout.version_matches(f"binary\n0.0.1\npinned\n{pinned}\n", pinned))
        self.assertFalse(cache_layout.version_matches(f"{pinned}\n", pinned))
        self.assertNotIn("npm", cache_layout.link_command())
        self.assertNotIn("nvm", cache_layout.probe_command())

    def test_ready_cache_skips_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ready_cache(Path(tmp))
            self.assertTrue(cache_layout.cache_ready(cache))

            def fail(*args, **kwargs):
                raise AssertionError("prefetch downloaded")

            with mock.patch("scripts.harbor.cache_layout.urllib.request.urlretrieve", fail):
                cache_layout.prefetch(cache)
            code = cache_layout.main(["--check", "--cache", str(cache)])
            self.assertEqual(code, 0)
            missing = cache_layout.main(["--check", "--cache", str(Path(tmp) / "missing")])
            self.assertEqual(missing, 1)

    def test_node_url_is_pinned(self):
        url = cache_layout.node_tarball_url(cache_layout.NODE_VERSION, "x86_64")
        self.assertIn("v22.21.0", url)
        self.assertIn("linux-x64", url)
        self.assertNotIn("latest", url)

    def test_cached_install_skips_npm_when_the_pin_matches(self):
        site = harbor_site_packages()
        self.assertIsNotNone(site)
        sys.path.insert(0, str(site))
        from scripts.harbor.opencode_cached import OpenCodeCached

        pinned = cache_layout.OPENCODE_VERSION
        hit = FakeEnv(0, f"binary\n{pinned}\npinned\n{pinned}\n")
        with tempfile.TemporaryDirectory() as tmp:
            agent = OpenCodeCached(logs_dir=Path(tmp))
            asyncio.run(agent.install(hit))
        self.assertTrue(any("ln -sfn" in command for command in hit.commands))
        self.assertFalse(any("npm" in command for command in hit.commands))

    def test_cached_install_falls_back_to_npm_on_a_miss(self):
        site = harbor_site_packages()
        self.assertIsNotNone(site)
        sys.path.insert(0, str(site))
        from scripts.harbor.opencode_cached import OpenCodeCached

        miss = FakeEnv(42, "")
        with tempfile.TemporaryDirectory() as tmp:
            agent = OpenCodeCached(logs_dir=Path(tmp))
            asyncio.run(agent.install(miss))
        self.assertTrue(any("npm i -g opencode-ai@" in command for command in miss.commands))
        self.assertFalse(any("ln -sfn" in command for command in miss.commands))


if __name__ == "__main__":
    unittest.main()
