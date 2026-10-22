#!/usr/bin/env python3
"""Single configuration contract for Scholar model serving and Harbor evals.

Precedence for every model setting is explicit CLI, then environment, then a
non-resolved config file, then the selected profile, then the legacy default.
A resolved config file is the remote handoff: environment does not override it,
and explicit CLI flags still do. This module does not allocate GPUs or start
llama-server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

CONTRACT_VERSION = 1
VERIFIED_LLAMA_COMMIT = "31288c9c66e59377f7788d920678a565bb89dd37"
VERIFIED_CUDA_ROOT = (
    "/apps/spack/scholar-dgx/apps/cuda/13.1.1-none-none-hfb3k4d"
)

DATASET_NOTE = (
    "Harbor's swebenchpro adapter on main, inspected 2026-10-20, calls "
    "load_dataset('ScaleAI/SWE-bench_Pro')['test'] with no config name and "
    "still documents 731 tasks plus jefzda/sweap-images. Hugging Face made "
    "SWE-bench Pro V2 (642 tasks, version 2.0.0) the default config on "
    "2026-09-22, kept the original 731-task release as config v1, and kept "
    "HARD-51 as config hard. A registry version such as swebenchpro@1.0 is "
    "not that release number. Do not pool scores across V1, V2, and HARD-51. "
    "swebench_release stays unverified until a live probe records the release."
)

LEGACY = {
    "model_hf": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
    "model_alias": "qwen3-4b",
    "context": 8192,
    "gpu_layers": 999,
    "flash_attn": "on",
    "parallel": 1,
    "port": 8080,
    "bind": "127.0.0.1",
    "cuda_managed": "auto",
    "output_limit": 4096,
    "smoke_max_tokens": 256,
    "reasoning": "preserve",
    "role": "legacy-default",
    "benchmark_ready": True,
    "note": (
        "Legacy default kept for existing scholar-session invocations: "
        "Qwen3-4B Q4_K_M, 8192 context, full offload, Flash Attention on. "
        "The recommended evaluation pilot is the qwen36-35b profile."
    ),
}

PROFILES: dict[str, dict[str, Any]] = {
    "smoke-4b": {
        "model_hf": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
        "model_alias": "qwen3-4b",
        "context": 16384,
        "gpu_layers": 999,
        "flash_attn": "on",
        "parallel": 1,
        "output_limit": 4096,
        "smoke_max_tokens": 256,
        "reasoning": "preserve",
        "benchmark_ready": True,
        "role": "infrastructure-smoke",
        "note": (
            "Infrastructure smoke profile. A 40960-token context failed in a "
            "pre-workaround test. Not the recommended benchmark."
        ),
    },
    "coder-14b": {
        "model_hf": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M",
        "model_alias": "qwen2.5-coder-14b",
        "context": 4096,
        "gpu_layers": 32,
        "flash_attn": "off",
        "parallel": 1,
        "output_limit": 1024,
        "smoke_max_tokens": 128,
        "reasoning": "preserve",
        "benchmark_ready": True,
        "role": "verified-load",
        "note": (
            "Verified on scholar-k060 on 2026-10-20 with the original "
            "llama.cpp build at commit 31288c9, CUDA 13.1.115, 32 GPU layers, "
            "Flash Attention off, and GGML_CUDA_ENABLE_UNIFIED_MEMORY=1. The "
            "server loaded and a two-token OK completion returned. A longer "
            "completion is not yet confirmed."
        ),
    },
    "qwen36-35b": {
        "model_hf": "unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M",
        "model_alias": "qwen36-35b",
        "context": 131072,
        "gpu_layers": 999,
        "flash_attn": "off",
        "parallel": 1,
        "output_limit": 8192,
        "smoke_max_tokens": 4096,
        "reasoning": "preserve",
        "benchmark_ready": True,
        "role": "evaluation-pilot",
        "note": (
            "Preferred current evaluation pilot. On scholar-k060 on 2026-10-20 "
            "the server initialized 131072 context and a short prompt produced "
            "a coherent final answer with finish_reason=stop (2377 generated "
            "tokens, about 50 generated tokens/s on that one request). Flash "
            "Attention was off. This does not establish long-prompt accuracy, "
            "tool-call reliability, or SWE-bench Pro success."
        ),
    },
    "qwen30b-diagnostic": {
        "model_hf": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q4_K_M",
        "model_alias": "qwen3-coder-30b",
        "context": 4096,
        "gpu_layers": 999,
        "flash_attn": "off",
        "parallel": 1,
        "output_limit": 1024,
        "smoke_max_tokens": 256,
        "reasoning": "preserve",
        "benchmark_ready": False,
        "role": "diagnostic",
        "note": (
            "Not benchmark-ready. After managed memory was enabled, this GGUF "
            "loaded, including at 131072 context, but completions were repeated "
            "characters. A successful load or a high tokens/sec figure is not a "
            "passing model."
        ),
    },
}

ENV_KEYS = {
    "model_profile": "MAGE_MODEL_PROFILE",
    "model_hf": "MAGE_MODEL_HF",
    "model_file": "MAGE_MODEL_FILE",
    "model_alias": "MAGE_MODEL_ALIAS",
    "model_revision": "MAGE_MODEL_REVISION",
    "context": "MAGE_CONTEXT",
    "gpu_layers": "MAGE_GPU_LAYERS",
    "flash_attn": "MAGE_FLASH_ATTN",
    "parallel": "MAGE_PARALLEL",
    "port": "MAGE_PORT",
    "bind": "MAGE_BIND",
    "cuda_managed": "MAGE_CUDA_MANAGED",
    "output_limit": "MAGE_OUTPUT_LIMIT",
    "smoke_max_tokens": "MAGE_SMOKE_MAX_TOKENS",
    "reasoning": "MAGE_REASONING",
    "temperature": "MAGE_TEMPERATURE",
    "llama_extra": "MAGE_LLAMA_EXTRA",
}

HF_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MEM_RE = re.compile(r"^[0-9]+([KMGT])?$", re.IGNORECASE)
TIME_RE = re.compile(
    r"^[0-9]+$|^[0-9]{1,2}:[0-9]{2}$|^[0-9]{1,2}:[0-9]{2}:[0-9]{2}$|"
    r"^[0-9]+-[0-9]{1,2}:[0-9]{2}:[0-9]{2}$"
)
PATH_RE = re.compile(r"^[~A-Za-z0-9_./@+-]+$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ConfigError(ValueError):
    """The requested configuration is malformed or not admissible."""


def dump(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"{label} must be a positive integer, got {value!r}.")
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ConfigError(f"{label} must be a base-10 integer, got {value!r}.")
    return int(text)


def _pick(
    key: str,
    cli: Mapping[str, Any],
    environ: Mapping[str, str],
    file_values: Mapping[str, Any] | None,
    profile_values: Mapping[str, Any],
    default: Any,
    resolved_mode: bool,
) -> tuple[Any, str]:
    if _present(cli.get(key)):
        return cli[key], "cli"
    if resolved_mode:
        if file_values is not None and key in file_values and file_values[key] is not None:
            return file_values[key], "file"
        return default, "default"
    env_name = ENV_KEYS.get(key)
    if env_name and _present(environ.get(env_name)):
        return environ[env_name], "env"
    if file_values is not None and _present(file_values.get(key)):
        return file_values[key], "file"
    if _present(profile_values.get(key)):
        return profile_values[key], "profile"
    return default, "default"


def _load_json_value(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read JSON {path}: {exc}") from exc


def _load_json(path: str) -> dict[str, Any]:
    data = _load_json_value(path)
    if not isinstance(data, dict):
        raise ConfigError(f"Config {path} must be a JSON object.")
    return data


def _llama_extra(
    cli: Mapping[str, Any],
    environ: Mapping[str, str],
    file_values: Mapping[str, Any] | None,
    resolved_mode: bool,
) -> list[str]:
    if cli.get("llama_extra"):
        values = list(cli["llama_extra"])
    elif resolved_mode:
        raw = (file_values or {}).get("llama_extra") or []
        if not isinstance(raw, list):
            raise ConfigError("llama_extra in a resolved config must be a list.")
        values = list(raw)
    elif _present(environ.get("MAGE_LLAMA_EXTRA")):
        values = shlex.split(str(environ["MAGE_LLAMA_EXTRA"]))
    elif file_values is not None and file_values.get("llama_extra"):
        raw = file_values["llama_extra"]
        if not isinstance(raw, list):
            raise ConfigError("llama_extra in a config file must be a list.")
        values = list(raw)
    else:
        return []
    cleaned = []
    for item in values:
        text = str(item)
        if text == "" or any(ch in text for ch in "\n\r\x00"):
            raise ConfigError(f"Refusing llama argument {text!r}.")
        cleaned.append(text)
    return cleaned


def resolve_config(
    cli: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_file: str | None = None,
    resolved_config: str | None = None,
) -> dict[str, Any]:
    cli = dict(cli or {})
    environ = dict(environ or {})
    if config_file and resolved_config:
        raise ConfigError("Pass only one of --config and --resolved-config.")
    resolved_mode = bool(resolved_config)
    file_values = _load_json(resolved_config or config_file) if (resolved_config or config_file) else None

    if _present(cli.get("model_profile")):
        profile_name = str(cli["model_profile"])
    elif resolved_mode:
        profile_name = str((file_values or {}).get("profile") or "")
    elif _present(environ.get("MAGE_MODEL_PROFILE")):
        profile_name = str(environ["MAGE_MODEL_PROFILE"])
    elif file_values is not None and _present(file_values.get("profile")):
        profile_name = str(file_values["profile"])
    else:
        profile_name = ""

    profile_values: dict[str, Any] = {}
    if profile_name:
        if profile_name not in PROFILES:
            known = ", ".join(sorted(PROFILES))
            raise ConfigError(f"Unknown model profile {profile_name!r}. Known profiles: {known}.")
        profile_values = PROFILES[profile_name]

    def pick(key: str, default: Any) -> Any:
        value, _source = _pick(key, cli, environ, file_values, profile_values, default, resolved_mode)
        return value

    def sourced(key: str, default: Any) -> tuple[Any, str]:
        return _pick(key, cli, environ, file_values, profile_values, default, resolved_mode)

    model_file, model_file_source = sourced("model_file", "")
    model_file = str(model_file or "")
    model_hf, model_hf_source = sourced("model_hf", "" if model_file else LEGACY["model_hf"])
    model_hf = str(model_hf or "")
    if model_hf and model_file:
        rank = {"cli": 4, "env": 3, "file": 2, "profile": 1, "default": 0}
        if rank[model_hf_source] > rank[model_file_source]:
            model_file = ""
        elif rank[model_file_source] > rank[model_hf_source]:
            model_hf = ""
        else:
            raise ConfigError("Pass either --model-hf or --model-file, not both.")
    if not model_hf and not model_file:
        raise ConfigError("A model is required. Pass --model-hf or --model-file.")
    if model_hf and not HF_RE.fullmatch(model_hf):
        raise ConfigError(
            f"Refusing model reference {model_hf!r}. Use a Hugging Face GGUF id such as "
            "org/name:QUANT with no spaces or shell metacharacters."
        )
    if model_file and any(ch in model_file for ch in "\n\r\x00"):
        raise ConfigError("Model file path contains a newline or NUL.")

    alias_default = profile_values.get("model_alias") or LEGACY["model_alias"]
    alias_explicit = _present(cli.get("model_alias")) or (
        not resolved_mode and _present(environ.get("MAGE_MODEL_ALIAS"))
    )
    if (
        model_hf
        and not profile_values
        and not alias_explicit
        and model_hf != LEGACY["model_hf"]
    ):
        alias_default = _derive_alias(model_hf)
    if (
        profile_values
        and model_hf
        and model_hf != profile_values.get("model_hf")
        and not alias_explicit
    ):
        raise ConfigError(
            "Overriding a profile's model requires an explicit --model-alias. "
            f"Refusing to reuse profile alias {profile_values.get('model_alias')!r}."
        )
    alias = str(pick("model_alias", alias_default))
    if not ALIAS_RE.fullmatch(alias):
        raise ConfigError(
            f"Model alias {alias!r} must be 1-128 characters of letters, digits, '.', '_', ':', or '-'."
        )

    context = _as_int(pick("context", LEGACY["context"]), "context")
    if context < 1:
        raise ConfigError("context must be a positive integer.")
    gpu_layers = _as_int(pick("gpu_layers", LEGACY["gpu_layers"]), "gpu-layers")
    if gpu_layers < 0:
        raise ConfigError("gpu-layers must be zero or greater.")
    parallel = _as_int(pick("parallel", LEGACY["parallel"]), "parallel")
    if parallel < 1:
        raise ConfigError("parallel must be a positive integer.")
    port = _as_int(pick("port", LEGACY["port"]), "port")
    if port < 1 or port > 65535:
        raise ConfigError("port must be between 1 and 65535.")

    flash = str(pick("flash_attn", LEGACY["flash_attn"])).lower()
    if flash not in {"on", "off", "auto"}:
        raise ConfigError("--flash-attn must be on, off, or auto.")
    cuda_managed = _normalize_managed(str(pick("cuda_managed", LEGACY["cuda_managed"])))
    reasoning = str(pick("reasoning", "preserve")).lower()
    if reasoning != "preserve":
        raise ConfigError(
            "This pipeline records reasoning and does not disable it. "
            "--reasoning only accepts 'preserve'. A flag that strips thinking "
            "has not been verified on the pinned llama.cpp build."
        )

    output_limit = _as_int(pick("output_limit", LEGACY["output_limit"]), "output-limit")
    smoke_max = _as_int(pick("smoke_max_tokens", LEGACY["smoke_max_tokens"]), "smoke-max-tokens")
    if output_limit < 1 or output_limit >= context:
        raise ConfigError(
            f"output limit {output_limit} must be a positive integer smaller than context {context}. "
            "No silent reduction was applied."
        )
    if smoke_max < 1 or smoke_max >= context:
        raise ConfigError(
            f"smoke max tokens {smoke_max} must be a positive integer smaller than context {context}. "
            "Pass --smoke-max-tokens or raise --context. No silent reduction was applied."
        )

    bind = str(pick("bind", LEGACY["bind"]))
    if any(ch in bind for ch in " \n\r\t"):
        raise ConfigError(f"Refusing bind address {bind!r}.")
    bind_public = bind not in {"127.0.0.1", "localhost"}

    temperature = str(pick("temperature", "") or "")
    if temperature:
        try:
            float(temperature)
        except ValueError as exc:
            raise ConfigError(f"temperature must be a number, got {temperature!r}.") from exc

    revision = str(pick("model_revision", "") or "")
    if any(ch in revision for ch in "\n\r\x00"):
        raise ConfigError("model revision contains a newline or NUL.")

    warnings: list[str] = []
    if parallel > 1:
        warnings.append(
            "This llama.cpp build divides -c by -np. "
            "The launcher sets -c to context times parallel so each slot gets the requested context."
        )
    if profile_name == "qwen36-35b" and flash != "off":
        warnings.append(
            "The known-working Qwen3.6 run used Flash Attention off. "
            "This invocation overrides that and should be compared separately."
        )
    if profile_name in {"qwen36-35b", "coder-14b"} and cuda_managed == "off":
        warnings.append(
            "The verified GB10 runs set GGML_CUDA_ENABLE_UNIFIED_MEMORY=1. "
            "cuda-managed=off is an explicit opt-out."
        )
    if not profile_values.get("benchmark_ready", True) and profile_name:
        warnings.append(str(profile_values.get("note") or "Profile is not benchmark-ready."))

    role = str(profile_values.get("role") or (file_values or {}).get("role") or LEGACY["role"])
    note = str(profile_values.get("note") or (file_values or {}).get("note") or LEGACY["note"])
    if profile_name:
        ready = bool(profile_values.get("benchmark_ready", True))
    elif file_values is not None and "benchmark_ready" in file_values:
        ready = bool(file_values["benchmark_ready"])
    else:
        ready = bool(LEGACY["benchmark_ready"])

    return {
        "contract_version": CONTRACT_VERSION,
        "profile": profile_name,
        "role": role,
        "note": note,
        "benchmark_ready": ready,
        "model_hf": model_hf,
        "model_file": model_file,
        "model_alias": alias,
        "model_revision": revision,
        "context": context,
        "gpu_layers": gpu_layers,
        "flash_attn": flash,
        "parallel": parallel,
        "port": port,
        "bind": bind,
        "bind_public": bind_public,
        "cuda_managed": cuda_managed,
        "output_limit": output_limit,
        "smoke_max_tokens": smoke_max,
        "reasoning": reasoning,
        "temperature": temperature,
        "llama_extra": _llama_extra(cli, environ, file_values, resolved_mode),
        "context_accounting": {
            "per_slot_context": context,
            "parallel_slots": parallel,
            "slots_times_context": context * parallel,
            "note": (
                "Requested context is per slot. This llama.cpp build divides -c by -np, "
                "so the launcher passes context times parallel as -c."
            ),
        },
        "warnings": warnings,
    }


def _derive_alias(model_hf: str) -> str:
    name = model_hf.split("/", 1)[-1].replace(":", "-").lower()
    name = re.sub(r"[^a-z0-9._-]+", "-", name).strip("-")
    name = name[:80] or "model"
    if not ALIAS_RE.fullmatch(name):
        raise ConfigError(f"Could not derive a stable alias from {model_hf!r}. Pass --model-alias.")
    return name


def _normalize_managed(value: str) -> str:
    text = value.strip().lower()
    if text in {"on", "1", "true", "yes"}:
        return "on"
    if text in {"off", "0", "false", "no"}:
        return "off"
    if text == "auto":
        return "auto"
    raise ConfigError("--cuda-managed must be on, off, or auto.")


def server_argv(resolved: Mapping[str, Any], binary: str) -> list[str]:
    # llama.cpp -c is the KV pool. With -np N the server gives each slot -c/N.
    slot_context = int(resolved["context"])
    slots = int(resolved["parallel"])
    argv = [
        binary,
        "-ngl",
        str(resolved["gpu_layers"]),
        "-c",
        str(slot_context * slots),
        "-np",
        str(slots),
        "-fa",
        str(resolved["flash_attn"]),
        "--jinja",
        "--alias",
        str(resolved["model_alias"]),
        "--host",
        str(resolved["bind"]),
        "--port",
        str(resolved["port"]),
    ]
    if resolved.get("model_file"):
        argv.extend(["-m", str(resolved["model_file"])])
    else:
        argv.extend(["-hf", str(resolved["model_hf"])])
    if resolved.get("temperature"):
        argv.extend(["--temp", str(resolved["temperature"])])
    argv.extend(str(item) for item in resolved.get("llama_extra") or [])
    return argv


def fingerprint(resolved: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    material = {
        "model_hf": resolved.get("model_hf") or "",
        "model_file": resolved.get("model_file") or "",
        "model_alias": resolved.get("model_alias") or "",
        "model_revision": resolved.get("model_revision") or "",
        "context": resolved.get("context"),
        "gpu_layers": resolved.get("gpu_layers"),
        "flash_attn": resolved.get("flash_attn"),
        "parallel": resolved.get("parallel"),
        "output_limit": resolved.get("output_limit"),
        "reasoning": resolved.get("reasoning"),
        "temperature": resolved.get("temperature") or "",
        "cuda_managed": resolved.get("cuda_managed"),
        "llama_extra": list(resolved.get("llama_extra") or []),
        "dataset": run.get("dataset") or "",
        "dataset_identity": run.get("dataset_identity") or "unverified",
        "n_tasks": run.get("n_tasks"),
        "task_ids": list(run.get("task_ids") or []),
        "condition": run.get("condition") or "",
        "llama_commit": run.get("llama_commit") or "unspecified",
        "n_concurrent": 1,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    condition = re.sub(r"[^A-Za-z0-9._-]+", "-", str(material["condition"]))[:24]
    dataset = re.sub(r"[^A-Za-z0-9._-]+", "-", str(material["dataset"]))[:40]
    alias = re.sub(r"[^A-Za-z0-9._-]+", "-", str(material["model_alias"]))[:40]
    job_name = f"mage-{dataset}-{condition}-n{material['n_tasks']}-{alias}-c{material['context']}-{digest}"
    return {"fingerprint": digest, "job_name": job_name, "material": material}


def is_repetitive(text: str) -> bool:
    compact = "".join(text.split())
    if len(compact) < 32:
        return False
    counts = Counter(compact)
    top = counts.most_common(1)[0][1]
    return top / len(compact) >= 0.85 and len(counts) <= 3


def _message(payload: Mapping[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ConfigError("Completion response has no choices.")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise ConfigError("Completion choice has no message object.")
    return {"choice": choices[0], "message": message}


def judge_chat(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        picked = _message(payload)
    except ConfigError as exc:
        return _verdict(False, str(exc), payload)
    choice = picked["choice"]
    message = picked["message"]
    content = message.get("content")
    content_text = content if isinstance(content, str) else ""
    reasoning = message.get("reasoning_content")
    if not isinstance(reasoning, str):
        reasoning = message.get("reasoning") if isinstance(message.get("reasoning"), str) else ""
    finish = str(choice.get("finish_reason") or "")
    verdict = _verdict(True, "", payload, content_text, reasoning, finish)
    if not content_text.strip():
        if reasoning.strip() and finish == "length":
            verdict.update(
                ok=False,
                reason=(
                    "The output budget was exhausted by reasoning_content and final content "
                    "is empty. Raise --smoke-max-tokens. A 512-token Qwen3.6 request failed "
                    "this way; a later 2377-token request returned final content."
                ),
            )
        else:
            verdict.update(ok=False, reason="Final content is empty.")
        return verdict
    if finish != "stop":
        verdict.update(
            ok=False,
            reason=f"finish_reason is {finish or 'missing'}; a smoke completion must finish with stop.",
        )
        return verdict
    if is_repetitive(content_text):
        verdict.update(
            ok=False,
            reason="Final content is repetitive. The Qwen3-Coder-30B diagnostic model produced this pattern.",
        )
        return verdict
    return verdict


def judge_tool_call(payload: Mapping[str, Any], expected_name: str = "echo") -> dict[str, Any]:
    try:
        message = _message(payload)["message"]
    except ConfigError as exc:
        return {"ok": False, "reason": str(exc), "tool_name": "", "arguments": {}}
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or not calls:
        return {
            "ok": False,
            "reason": "The model did not emit a tool call. A chat reply does not prove OpenCode tool use.",
            "tool_name": "",
            "arguments": {},
        }
    call = calls[0] if isinstance(calls[0], dict) else {}
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    raw_args = function.get("arguments")
    if isinstance(raw_args, str):
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "Tool arguments are not valid JSON.", "tool_name": name, "arguments": {}}
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        arguments = {}
    if name != expected_name:
        return {
            "ok": False,
            "reason": f"Tool name {name!r} does not match {expected_name!r}.",
            "tool_name": name,
            "arguments": arguments,
        }
    text = arguments.get("text") if isinstance(arguments, dict) else None
    if not isinstance(text, str) or "hello" not in text.lower():
        return {
            "ok": False,
            "reason": "Tool arguments did not include text containing hello.",
            "tool_name": name,
            "arguments": arguments if isinstance(arguments, dict) else {},
        }
    if not re.fullmatch(r"[A-Za-z0-9 ._:-]{1,80}", text):
        return {
            "ok": False,
            "reason": "Tool argument is not a plain echo string. It was not executed.",
            "tool_name": name,
            "arguments": arguments,
        }
    return {
        "ok": True,
        "reason": "",
        "tool_name": name,
        "arguments": arguments,
        "tool_call_id": str(call.get("id") or "call_smoke"),
        "echo_text": text,
    }


def judge_loaded_model(
    alias: str,
    requested_context: int,
    models: Mapping[str, Any] | None,
    slots: Any = None,
    props: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = []
    if isinstance(models, Mapping):
        data = models.get("data")
        if isinstance(data, list):
            rows = [row for row in data if isinstance(row, dict)]
    ids = [str(row.get("id") or "") for row in rows]
    reported, conflict = _extract_n_ctx(slots, props)
    if alias not in ids:
        return {
            "ok": False,
            "reason": f"Server model ids {ids or ['(none)']} do not include requested alias {alias}.",
            "model_ids": ids,
            "n_ctx": reported,
        }
    if conflict:
        return {
            "ok": False,
            "reason": conflict,
            "model_ids": ids,
            "n_ctx": None,
        }
    if reported is None:
        return {
            "ok": False,
            "reason": (
                "The server did not report slot n_ctx on /slots or /props. "
                "n_ctx_train from the model card is not the loaded context."
            ),
            "model_ids": ids,
            "n_ctx": None,
        }
    if reported != int(requested_context):
        return {
            "ok": False,
            "reason": f"Server n_ctx is {reported}, requested context is {requested_context}.",
            "model_ids": ids,
            "n_ctx": reported,
        }
    return {"ok": True, "reason": "", "model_ids": ids, "n_ctx": reported}


def _extract_n_ctx(slots: Any, props: Mapping[str, Any] | None) -> tuple[int | None, str]:
    found: list[int] = []

    def take(value: Any) -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            found.append(int(value))

    slot_rows: list[Any] = []
    if isinstance(slots, list):
        slot_rows = slots
    elif isinstance(slots, Mapping):
        take(slots.get("n_ctx"))
        nested = slots.get("slots")
        if isinstance(nested, list):
            slot_rows = nested
    for slot in slot_rows:
        if isinstance(slot, Mapping):
            take(slot.get("n_ctx"))
    if isinstance(props, Mapping):
        settings = props.get("default_generation_settings")
        if isinstance(settings, Mapping) and "n_ctx" in settings:
            take(settings.get("n_ctx"))
        elif "n_ctx" in props:
            take(props.get("n_ctx"))
    if not found:
        return None, ""
    if any(item != found[0] for item in found):
        return None, f"Server reported conflicting n_ctx values: {found}."
    return found[0], ""


def _verdict(
    ok: bool,
    reason: str,
    payload: Mapping[str, Any],
    content: str = "",
    reasoning: str = "",
    finish: str = "",
) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    return {
        "ok": ok,
        "reason": reason,
        "content": content,
        "reasoning_content": reasoning,
        "finish_reason": finish,
        "usage": usage,
        "timings": timings,
    }


def render_opencode(base_url: str, resolved: Mapping[str, Any]) -> dict[str, Any]:
    alias = str(resolved["model_alias"])
    return {
        "provider": {
            "scholar": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Scholar GPU",
                "options": {"baseURL": base_url, "apiKey": "local"},
                "models": {
                    alias: {
                        "name": alias,
                        "limit": {
                            "context": int(resolved["context"]),
                            "output": int(resolved["output_limit"]),
                        },
                    }
                },
            }
        },
        "model": f"scholar/{alias}",
    }


def classify_dataset_probe(dataset: str, harbor_version: str, list_output: str) -> dict[str, Any]:
    token = None
    for match in re.finditer(r"([A-Za-z0-9_./+-]+)@([A-Za-z0-9._-]+)", list_output or ""):
        name = match.group(1)
        if dataset == name or dataset in name or name.endswith(dataset):
            token = match.group(0)
            break
    release = "unverified"
    lowered = list_output or ""
    if "HARD-51" in lowered or '"hard"' in lowered:
        release = "unverified-hard-mentioned"
    return {
        "requested_dataset": dataset,
        "harbor_version": harbor_version or "",
        "registry_token": token,
        "swebench_release": release if release == "unverified" else "unverified",
        "identity": token or "unverified",
        "note": DATASET_NOTE,
    }


def validate_allocation(allocation: Mapping[str, Any]) -> dict[str, Any]:
    account = str(allocation.get("account") or "")
    partition = str(allocation.get("partition") or "")
    qos = str(allocation.get("qos") or "")
    mem = str(allocation.get("mem") or "")
    wall = str(allocation.get("time") or "")
    gpus = _as_int(allocation.get("gpus"), "gpus")
    cpus = _as_int(allocation.get("cpus"), "cpus")
    if not ACCOUNT_RE.fullmatch(account):
        raise ConfigError(f"Refusing SLURM account {account!r}.")
    if not ACCOUNT_RE.fullmatch(partition):
        raise ConfigError(f"Refusing SLURM partition {partition!r}.")
    if qos and not ACCOUNT_RE.fullmatch(qos):
        raise ConfigError(f"Refusing SLURM QoS {qos!r}.")
    if not MEM_RE.fullmatch(mem):
        raise ConfigError(f"Refusing memory value {mem!r}. Example: 100G.")
    if not TIME_RE.fullmatch(wall):
        raise ConfigError(f"Refusing walltime {wall!r}. Example: 02:00:00 or 0-04:00:00.")
    if gpus < 1 or gpus > 8:
        raise ConfigError("gpus must be from 1 to 8 for this Scholar launcher.")
    if cpus < 1 or cpus > 128:
        raise ConfigError("cpus must be from 1 to 128 for this Scholar launcher.")
    warnings = []
    if _wall_seconds(wall) <= 2 * 60 * 60:
        warnings.append(
            "A two-hour GPU allocation may be insufficient for a full SWE-bench Pro run. "
            "Request a longer approved walltime or resume the same Harbor job on a later allocation."
        )
    cleaned = {
        "account": account,
        "partition": partition,
        "qos": qos,
        "gpus": gpus,
        "cpus": cpus,
        "mem": mem,
        "time": wall,
        "job_name": str(allocation.get("job_name") or ""),
        "warnings": warnings,
    }
    if cleaned["job_name"] and not RUN_ID_RE.fullmatch(cleaned["job_name"]):
        raise ConfigError(f"Refusing job name {cleaned['job_name']!r}.")
    return cleaned


def _wall_seconds(wall: str) -> int:
    if wall.isdigit():
        return int(wall) * 60
    days = 0
    clock = wall
    if "-" in wall:
        day_text, clock = wall.split("-", 1)
        days = int(day_text)
    parts = [int(part) for part in clock.split(":")]
    if len(parts) == 2:
        hours, minutes, seconds = 0, parts[0], parts[1]
    else:
        hours, minutes, seconds = parts
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def render_sbatch(
    allocation: Mapping[str, Any],
    run_dir: str,
    run_id: str,
    repo_or_launcher: str,
    scratch: str = "",
    llama_commit: str = "",
) -> str:
    cleaned = validate_allocation(allocation)
    for label, value in (("run dir", run_dir), ("launcher", repo_or_launcher), ("run id", run_id)):
        if not PATH_RE.fullmatch(value) and not RUN_ID_RE.fullmatch(value):
            raise ConfigError(f"Refusing {label} {value!r} in the batch script.")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ConfigError(f"Refusing run id {run_id!r}.")
    if not PATH_RE.fullmatch(run_dir) or not PATH_RE.fullmatch(repo_or_launcher):
        raise ConfigError("Batch paths must be plain absolute or tilde paths.")
    scratch_line = ""
    if scratch:
        if not PATH_RE.fullmatch(scratch):
            raise ConfigError(f"Refusing scratch path {scratch!r}.")
        scratch_line = f"export MAGE_SCRATCH={scratch!r}\n"
    commit_args = ""
    if llama_commit:
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", llama_commit):
            raise ConfigError(f"Refusing llama commit {llama_commit!r}.")
        commit_args = f" --llama-commit {llama_commit}"
    job_name = cleaned["job_name"] or f"mage-{run_id}"
    if not RUN_ID_RE.fullmatch(job_name):
        raise ConfigError(f"Refusing job name {job_name!r}.")
    qos = f"#SBATCH --qos={cleaned['qos']}\n" if cleaned["qos"] else ""
    return f"""#!/bin/bash
#SBATCH --account={cleaned['account']}
#SBATCH --partition={cleaned['partition']}
#SBATCH --gres=gpu:{cleaned['gpus']}
#SBATCH --cpus-per-task={cleaned['cpus']}
#SBATCH --mem={cleaned['mem']}
#SBATCH --time={cleaned['time']}
#SBATCH --job-name={job_name}
#SBATCH --output={run_dir}/slurm-%j.out
#SBATCH --error={run_dir}/slurm-%j.err
#SBATCH --chdir={run_dir}
{qos}set -euo pipefail
if [[ -z "${{HOME:-}}" || ! -d "${{HOME:-}}" ]]; then
  _user="$(id -un)"
  HOME="$(getent passwd "${{_user}}" | awk -F: '{{print $6}}')"
  export HOME
fi
if [[ -z "${{HOME:-}}" || ! -d "${{HOME:-}}" ]]; then
  echo "HOME is unset in this batch shell and passwd lookup failed." >&2
  exit 2
fi
mkdir -p {run_dir}
hostname > {run_dir}/hostname
printf '%s\\n' "${{SLURM_JOB_ID:-}}" > {run_dir}/jobid
python3 - <<'PY'
import json, os, socket
from pathlib import Path
path = Path({run_dir!r}) / "allocation.json"
payload = {{
  "job_id": os.environ.get("SLURM_JOB_ID", ""),
  "job_name": {job_name!r},
  "hostname": socket.gethostname(),
  "nodelist": os.environ.get("SLURM_JOB_NODELIST", ""),
  "owned": True,
}}
path.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
PY
{scratch_line}exec bash {repo_or_launcher!r} serve --foreground --resolved-config {run_dir!r}/model-config.json{commit_args}
"""


def chat_request(resolved: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": resolved["model_alias"],
        "temperature": 0,
        "max_tokens": int(resolved["smoke_max_tokens"]),
        "messages": [
            {
                "role": "user",
                "content": "Answer with one short sentence: what is two plus two?",
            }
        ],
    }


def tool_request(resolved: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": resolved["model_alias"],
        "temperature": 0,
        "max_tokens": int(resolved["smoke_max_tokens"]),
        "messages": [
            {
                "role": "user",
                "content": "Use the echo tool. Pass text exactly hello.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo text.",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }
        ],
    }


def tool_followup(resolved: Mapping[str, Any], tool_verdict: Mapping[str, Any]) -> dict[str, Any]:
    echo = str(tool_verdict.get("echo_text") or "")
    return {
        "model": resolved["model_alias"],
        "temperature": 0,
        "max_tokens": int(resolved["smoke_max_tokens"]),
        "messages": [
            {"role": "user", "content": "Use the echo tool. Pass text exactly hello."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_verdict.get("tool_call_id") or "call_smoke",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": json.dumps({"text": echo}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": tool_verdict.get("tool_call_id") or "call_smoke",
                "content": echo,
            },
        ],
    }


def summarize_harbor_tree(root: str) -> dict[str, Any]:
    base = Path(root)
    rewards = []
    if base.is_dir():
        for path in base.rglob("result.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                rewards.append({"path": str(path), "reward": None, "error": "unreadable"})
                continue
            reward = None
            verifier = payload.get("verifier_result") if isinstance(payload, dict) else None
            if isinstance(verifier, dict):
                values = verifier.get("rewards")
                if isinstance(values, dict) and "reward" in values:
                    reward = values.get("reward")
            usage = {}
            agent = payload.get("agent_result") if isinstance(payload, dict) else None
            if isinstance(agent, dict):
                for key in ("n_input_tokens", "n_output_tokens", "n_cache_tokens"):
                    if key in agent:
                        usage[key] = agent.get(key)
            rewards.append({"path": str(path), "reward": reward, "usage": usage})
    return {
        "result_files": len(rewards),
        "results": rewards,
        "note": "A single smoke task is not an aggregate SWE-bench Pro score.",
    }


def _cli_from_args(args: argparse.Namespace) -> dict[str, Any]:
    cli: dict[str, Any] = {}
    for key in (
        "model_profile",
        "model_hf",
        "model_file",
        "model_alias",
        "model_revision",
        "context",
        "gpu_layers",
        "flash_attn",
        "parallel",
        "port",
        "bind",
        "cuda_managed",
        "output_limit",
        "smoke_max_tokens",
        "reasoning",
        "temperature",
    ):
        value = getattr(args, key)
        if value is not None:
            cli[key] = value
    if args.llama_arg:
        cli["llama_extra"] = args.llama_arg
    return cli


def _add_model_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model-profile")
    parser.add_argument("--model-hf")
    parser.add_argument("--model-file")
    parser.add_argument("--model-alias")
    parser.add_argument("--model-revision")
    parser.add_argument("--context")
    parser.add_argument("--gpu-layers")
    parser.add_argument("--flash-attn")
    parser.add_argument("--parallel")
    parser.add_argument("--port")
    parser.add_argument("--bind")
    parser.add_argument("--cuda-managed")
    parser.add_argument("--output-limit")
    parser.add_argument("--smoke-max-tokens")
    parser.add_argument("--reasoning")
    parser.add_argument("--temperature")
    parser.add_argument("--llama-arg", action="append")
    parser.add_argument("--config")
    parser.add_argument("--resolved-config")
    parser.add_argument("--ignore-environment", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mage_scholar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    resolve_parser = sub.add_parser("resolve")
    _add_model_flags(resolve_parser)

    argv_parser = sub.add_parser("argv")
    argv_parser.add_argument("--resolved", required=True)
    argv_parser.add_argument("--binary", required=True)
    argv_parser.add_argument("--print0", action="store_true")

    finger = sub.add_parser("fingerprint")
    finger.add_argument("--resolved", required=True)
    finger.add_argument("--dataset", required=True)
    finger.add_argument("--dataset-identity", default="unverified")
    finger.add_argument("--n-tasks", required=True)
    finger.add_argument("--condition", required=True)
    finger.add_argument("--llama-commit", default="unspecified")
    finger.add_argument("--task-id", action="append", default=[])

    judge = sub.add_parser("judge-chat")
    judge.add_argument("response")
    loaded = sub.add_parser("judge-models")
    loaded.add_argument("--alias", required=True)
    loaded.add_argument("--context", required=True)
    loaded.add_argument("--models", required=True)
    loaded.add_argument("--slots")
    loaded.add_argument("--props")
    tool = sub.add_parser("judge-tool")
    tool.add_argument("response")
    opencode = sub.add_parser("opencode")
    opencode.add_argument("--resolved", required=True)
    opencode.add_argument("--base-url", required=True)
    probe = sub.add_parser("classify-dataset")
    probe.add_argument("--dataset", required=True)
    probe.add_argument("--version", default="")
    probe.add_argument("--list-file", required=True)
    sbatch = sub.add_parser("sbatch")
    sbatch.add_argument("--allocation", required=True)
    sbatch.add_argument("--run-dir", required=True)
    sbatch.add_argument("--run-id", required=True)
    sbatch.add_argument("--launcher", required=True)
    sbatch.add_argument("--scratch", default="")
    sbatch.add_argument("--llama-commit", default="")
    request = sub.add_parser("chat-request")
    request.add_argument("--resolved", required=True)
    tool_req = sub.add_parser("tool-request")
    tool_req.add_argument("--resolved", required=True)
    follow = sub.add_parser("tool-followup")
    follow.add_argument("--resolved", required=True)
    follow.add_argument("--verdict", required=True)
    summary = sub.add_parser("summarize-harbor")
    summary.add_argument("--root", required=True)
    sub.add_parser("dataset-note")
    sub.add_parser("profiles")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "resolve":
            environ: Mapping[str, str] = {} if args.ignore_environment else dict(os_environ())
            payload = resolve_config(
                _cli_from_args(args),
                environ,
                args.config,
                args.resolved_config,
            )
            sys.stdout.write(dump(payload))
        elif args.cmd == "argv":
            resolved = _load_json(args.resolved)
            command = server_argv(resolved, args.binary)
            if args.print0:
                sys.stdout.buffer.write(b"\0".join(part.encode() for part in command) + b"\0")
            else:
                sys.stdout.write(dump({"argv": command}))
        elif args.cmd == "fingerprint":
            payload = fingerprint(
                _load_json(args.resolved),
                {
                    "dataset": args.dataset,
                    "dataset_identity": args.dataset_identity,
                    "n_tasks": int(args.n_tasks),
                    "condition": args.condition,
                    "llama_commit": args.llama_commit,
                    "task_ids": args.task_id,
                },
            )
            sys.stdout.write(dump(payload))
        elif args.cmd == "judge-chat":
            sys.stdout.write(dump(judge_chat(_load_json(args.response))))
        elif args.cmd == "judge-models":
            slots = _load_json_value(args.slots) if args.slots else None
            props = _load_json(args.props) if args.props else None
            sys.stdout.write(
                dump(
                    judge_loaded_model(
                        args.alias,
                        int(args.context),
                        _load_json(args.models),
                        slots,
                        props,
                    )
                )
            )
        elif args.cmd == "judge-tool":
            sys.stdout.write(dump(judge_tool_call(_load_json(args.response))))
        elif args.cmd == "opencode":
            sys.stdout.write(dump(render_opencode(args.base_url, _load_json(args.resolved))))
        elif args.cmd == "classify-dataset":
            text = Path(args.list_file).read_text(encoding="utf-8")
            sys.stdout.write(dump(classify_dataset_probe(args.dataset, args.version, text)))
        elif args.cmd == "sbatch":
            sys.stdout.write(
                render_sbatch(
                    _load_json(args.allocation),
                    args.run_dir,
                    args.run_id,
                    args.launcher,
                    scratch=args.scratch,
                    llama_commit=args.llama_commit,
                )
            )
        elif args.cmd == "chat-request":
            sys.stdout.write(dump(chat_request(_load_json(args.resolved))))
        elif args.cmd == "tool-request":
            sys.stdout.write(dump(tool_request(_load_json(args.resolved))))
        elif args.cmd == "tool-followup":
            sys.stdout.write(dump(tool_followup(_load_json(args.resolved), _load_json(args.verdict))))
        elif args.cmd == "summarize-harbor":
            sys.stdout.write(dump(summarize_harbor_tree(args.root)))
        elif args.cmd == "dataset-note":
            sys.stdout.write(dump({"note": DATASET_NOTE, "swebench_release": "unverified"}))
        elif args.cmd == "profiles":
            sys.stdout.write(dump({"profiles": PROFILES, "legacy": LEGACY}))
        else:
            raise ConfigError(f"Unknown command {args.cmd}")
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    return 0


def os_environ() -> Mapping[str, str]:
    import os

    return os.environ


if __name__ == "__main__":
    raise SystemExit(main())
