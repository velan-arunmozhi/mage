import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import mage_scholar


def chat(content, finish="stop", reasoning=""):
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        "timings": {"predicted_per_second": 6.86, "predicted_n": 2},
    }


class ResolveTests(unittest.TestCase):
    def test_legacy_default(self):
        resolved = mage_scholar.resolve_config({}, {})
        self.assertEqual(resolved["model_hf"], "Qwen/Qwen3-4B-GGUF:Q4_K_M")
        self.assertEqual(resolved["model_alias"], "qwen3-4b")
        self.assertEqual(resolved["context"], 8192)
        self.assertEqual(resolved["flash_attn"], "on")
        self.assertEqual(resolved["gpu_layers"], 999)
        self.assertTrue(resolved["benchmark_ready"])

    def test_precedence_cli_over_env_over_profile(self):
        resolved = mage_scholar.resolve_config(
            {"model_profile": "qwen36-35b", "context": "32768", "output_limit": "1024", "smoke_max_tokens": "256"},
            {"MAGE_CONTEXT": "8192", "MAGE_FLASH_ATTN": "on"},
        )
        self.assertEqual(resolved["context"], 32768)
        self.assertEqual(resolved["flash_attn"], "on")
        self.assertEqual(resolved["model_hf"], "unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M")
        self.assertEqual(resolved["model_alias"], "qwen36-35b")
        self.assertIn("Flash Attention off", " ".join(resolved["warnings"]))

    def test_env_overrides_profile_context(self):
        resolved = mage_scholar.resolve_config(
            {"model_profile": "qwen36-35b"},
            {"MAGE_CONTEXT": "8192", "MAGE_OUTPUT_LIMIT": "1024", "MAGE_SMOKE_MAX_TOKENS": "512"},
        )
        self.assertEqual(resolved["context"], 8192)
        self.assertEqual(resolved["flash_attn"], "off")
        self.assertEqual(resolved["gpu_layers"], 999)

    def test_profile_values(self):
        coder = mage_scholar.resolve_config({"model_profile": "coder-14b"}, {})
        self.assertEqual(coder["gpu_layers"], 32)
        self.assertEqual(coder["context"], 4096)
        self.assertEqual(coder["flash_attn"], "off")
        self.assertEqual(coder["model_alias"], "qwen2.5-coder-14b")
        diagnostic = mage_scholar.resolve_config({"model_profile": "qwen30b-diagnostic"}, {})
        self.assertFalse(diagnostic["benchmark_ready"])
        self.assertEqual(diagnostic["context"], 4096)

    def test_resolved_config_ignores_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolved.json"
            path.write_text(
                json.dumps(
                    {
                        "profile": "coder-14b",
                        "model_hf": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M",
                        "model_alias": "qwen2.5-coder-14b",
                        "context": 4096,
                        "gpu_layers": 32,
                        "flash_attn": "off",
                        "parallel": 1,
                        "port": 8080,
                        "bind": "127.0.0.1",
                        "cuda_managed": "auto",
                        "output_limit": 1024,
                        "smoke_max_tokens": 128,
                        "reasoning": "preserve",
                        "benchmark_ready": True,
                        "llama_extra": ["--temp", "0"],
                    }
                ),
                encoding="utf-8",
            )
            resolved = mage_scholar.resolve_config(
                {},
                {"MAGE_CONTEXT": "131072", "MAGE_MODEL_HF": "Qwen/Qwen3-4B-GGUF:Q4_K_M"},
                resolved_config=str(path),
            )
        self.assertEqual(resolved["context"], 4096)
        self.assertEqual(resolved["model_hf"], "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M")
        self.assertEqual(resolved["llama_extra"], ["--temp", "0"])

    def test_rejects_bad_combinations(self):
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config({"context": "0"}, {})
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config({"model_profile": "missing"}, {})
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config({"model_hf": "org/name;rm", "model_alias": "bad"}, {})
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config(
                {"model_profile": "qwen36-35b", "output_limit": "131072"},
                {},
            )
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config({"reasoning": "off"}, {})
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.resolve_config(
                {"model_profile": "qwen36-35b", "model_hf": "org/Other:Q4_K_M"},
                {},
            )

    def test_explicit_alias_can_override_profile_model(self):
        resolved = mage_scholar.resolve_config(
            {
                "model_profile": "smoke-4b",
                "model_hf": "org/Custom-GGUF:Q4_K_M",
                "model_alias": "custom",
                "context": "2048",
                "output_limit": "256",
                "smoke_max_tokens": "64",
            },
            {},
        )
        self.assertEqual(resolved["model_alias"], "custom")
        self.assertEqual(resolved["context"], 2048)
        argv = mage_scholar.server_argv(resolved, "llama-server")
        self.assertIn("org/Custom-GGUF:Q4_K_M", argv)
        self.assertNotIn("Qwen/Qwen3-4B-GGUF:Q4_K_M", argv)
        self.assertEqual(argv[argv.index("-c") + 1], "2048")

    def test_qwen36_argv_uses_known_working_flags(self):
        resolved = mage_scholar.resolve_config({"model_profile": "qwen36-35b"}, {})
        argv = mage_scholar.server_argv(resolved, "/opt/llama-server")
        self.assertEqual(argv[0], "/opt/llama-server")
        self.assertEqual(argv[argv.index("-c") + 1], "131072")
        self.assertEqual(argv[argv.index("-fa") + 1], "off")
        self.assertEqual(argv[argv.index("-ngl") + 1], "999")
        self.assertEqual(argv[argv.index("--alias") + 1], "qwen36-35b")
        self.assertIn("--jinja", argv)
        self.assertIn("unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M", argv)
        self.assertNotIn("LLAMA_CURL", argv)
        self.assertNotIn("Qwen3-4B", " ".join(argv))


class FingerprintTests(unittest.TestCase):
    def test_same_config_is_stable_and_context_changes_the_job(self):
        left = mage_scholar.resolve_config({"model_profile": "qwen36-35b"}, {})
        right = mage_scholar.resolve_config(
            {"model_profile": "qwen36-35b", "context": "8192", "output_limit": "1024", "smoke_max_tokens": "512"},
            {},
        )
        run = {
            "dataset": "swebenchpro",
            "dataset_identity": "unverified",
            "n_tasks": 1,
            "task_ids": [],
            "condition": "baseline",
            "llama_commit": "unspecified",
        }
        first = mage_scholar.fingerprint(left, run)
        again = mage_scholar.fingerprint(left, run)
        other = mage_scholar.fingerprint(right, run)
        self.assertEqual(first["fingerprint"], again["fingerprint"])
        self.assertEqual(first["job_name"], again["job_name"])
        self.assertNotEqual(first["job_name"], other["job_name"])
        self.assertNotIn("qwen3-4b", first["job_name"])
        mage_run = dict(run, condition="mage")
        self.assertNotEqual(first["job_name"], mage_scholar.fingerprint(left, mage_run)["job_name"])


class SmokeTests(unittest.TestCase):
    def test_short_answer_passes_and_repetition_fails(self):
        ok = mage_scholar.judge_chat(chat("Two plus two is 4."))
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["timings"]["predicted_n"], 2)
        for token in ("G", "3", "/"):
            verdict = mage_scholar.judge_chat(chat(token * 64))
            self.assertFalse(verdict["ok"], token)
        budget = mage_scholar.judge_chat(chat("", finish="length", reasoning="thinking " * 20))
        self.assertFalse(budget["ok"])
        self.assertIn("output budget", budget["reason"])
        self.assertTrue(budget["reasoning_content"])

    def test_tool_call_and_model_identity(self):
        good = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "echo", "arguments": "{\"text\":\"hello\"}"},
                            }
                        ],
                    },
                }
            ]
        }
        verdict = mage_scholar.judge_tool_call(good)
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["echo_text"], "hello")
        prose = mage_scholar.judge_tool_call(chat("hello"))
        self.assertFalse(prose["ok"])
        models = {"data": [{"id": "qwen36-35b", "meta": {"n_ctx_train": 262144}}]}
        missing = mage_scholar.judge_loaded_model("qwen36-35b", 131072, models, [], {})
        self.assertFalse(missing["ok"])
        self.assertIn("n_ctx_train", missing["reason"])
        matched = mage_scholar.judge_loaded_model(
            "qwen36-35b",
            131072,
            models,
            [{"id": 0, "n_ctx": 131072}],
            {},
        )
        self.assertTrue(matched["ok"])
        wrong = mage_scholar.judge_loaded_model(
            "qwen3-4b",
            8192,
            {"data": [{"id": "qwen36-35b"}]},
            [{"n_ctx": 8192}],
            {},
        )
        self.assertFalse(wrong["ok"])

    def test_opencode_limits_come_from_the_resolved_server(self):
        resolved = mage_scholar.resolve_config({"model_profile": "qwen36-35b"}, {})
        config = mage_scholar.render_opencode("http://127.0.0.1:18080/v1", resolved)
        model = config["provider"]["scholar"]["models"]["qwen36-35b"]
        self.assertEqual(model["limit"]["context"], 131072)
        self.assertEqual(model["limit"]["output"], 8192)
        self.assertEqual(config["model"], "scholar/qwen36-35b")
        self.assertNotIn("qwen3-4b", json.dumps(config))


class DatasetAndBatchTests(unittest.TestCase):
    def test_dataset_probe_does_not_invent_v2(self):
        empty = mage_scholar.classify_dataset_probe("swebenchpro", "harbor 0.1.0", "")
        self.assertEqual(empty["identity"], "unverified")
        self.assertEqual(empty["swebench_release"], "unverified")
        listed = mage_scholar.classify_dataset_probe(
            "swebenchpro",
            "harbor 0.1.0",
            "swebenchpro@1.0\nscale-ai/swe-bench-pro@latest\n",
        )
        self.assertEqual(listed["identity"], "swebenchpro@1.0")
        self.assertEqual(listed["swebench_release"], "unverified")
        self.assertIn("V2", listed["note"])

    def test_sbatch_rejects_injection_and_records_the_verified_shape(self):
        script = mage_scholar.render_sbatch(
            {
                "account": "scholar",
                "partition": "spark-batch",
                "gpus": 1,
                "cpus": 20,
                "mem": "100G",
                "time": "02:00:00",
                "qos": "",
                "job_name": "mage-run-1",
            },
            "/home/user/mage-eval-jobs/run-1",
            "run-1",
            "/home/user/mage-eval-jobs/run-1/scholar-session",
        )
        self.assertIn("#SBATCH --account=scholar", script)
        self.assertIn("#SBATCH --partition=spark-batch", script)
        self.assertIn("--gres=gpu:1", script)
        self.assertIn("serve --foreground --resolved-config", script)
        pinned = mage_scholar.render_sbatch(
            {
                "account": "scholar",
                "partition": "spark-batch",
                "gpus": 1,
                "cpus": 20,
                "mem": "100G",
                "time": "02:00:00",
                "qos": "",
                "job_name": "mage-run-1",
            },
            "/home/user/mage-eval-jobs/run-1",
            "run-1",
            "/home/user/mage-eval-jobs/run-1/scholar-session",
            scratch="/scratch/scholar/user/bench",
            llama_commit="31288c9",
        )
        self.assertIn("export MAGE_SCRATCH='/scratch/scholar/user/bench'", pinned)
        self.assertIn("--llama-commit 31288c9", pinned)
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.render_sbatch(
                {
                    "account": "scholar",
                    "partition": "spark-batch",
                    "gpus": 1,
                    "cpus": 20,
                    "mem": "100G",
                    "time": "02:00:00",
                    "qos": "",
                    "job_name": "mage-run-1",
                },
                "/home/user/mage-eval-jobs/run-1",
                "run-1",
                "/home/user/mage-eval-jobs/run-1/scholar-session",
                scratch="/tmp/bad scratch",
            )
        self.assertIn("two-hour", " ".join(mage_scholar.validate_allocation({
            "account": "scholar",
            "partition": "spark-batch",
            "gpus": 1,
            "cpus": 20,
            "mem": "100G",
            "time": "02:00:00",
        })["warnings"]))
        with self.assertRaises(mage_scholar.ConfigError):
            mage_scholar.validate_allocation(
                {
                    "account": "scholar;rm",
                    "partition": "spark-batch",
                    "gpus": 1,
                    "cpus": 20,
                    "mem": "100G",
                    "time": "02:00:00",
                }
            )


if __name__ == "__main__":
    unittest.main()
