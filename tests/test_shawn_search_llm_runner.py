import importlib.util
import sys
from pathlib import Path


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_shawn_search_llm.py"
    spec = importlib.util.spec_from_file_location("run_shawn_search_llm", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_max_profile_builds_high_performance_chain(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(
        [
            "--query",
            "endometrial organoid",
            "--claim",
            "organoids model uterine biology",
            "--quality",
            "max",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "gpt-oss:120b-cloud"
    assert profile.fallback_chain.startswith("gpt-oss:120b-cloud,deepseek-v4-flash:cloud,kimi-k2.6:cloud")
    assert profile.llm_limit == 50
    assert "--llm-triage" in cmd
    assert "--llm-rerank" in cmd
    assert "--fast" in cmd
    assert cmd[cmd.index("--llm-model") + 1] == "gpt-oss:120b-cloud"


def test_deep_profile_prefers_deepseek_flash(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "deep"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "deepseek-v4-flash:cloud"
    assert profile.fallback_chain.startswith("deepseek-v4-flash:cloud,gpt-oss:120b-cloud")
    assert cmd[cmd.index("--llm-limit") + 1] == "30"


def test_agent_profile_prefers_kimi_cloud(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "agent"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "kimi-k2.6:cloud"
    assert profile.fallback_chain.startswith("kimi-k2.6:cloud,qwen3-coder:480b-cloud")
    assert cmd[cmd.index("--llm-model") + 1] == "kimi-k2.6:cloud"


def test_fast_profile_prefers_value_cloud(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "fast"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "gpt-oss:20b-cloud"
    assert profile.fallback_chain == "gpt-oss:20b-cloud,code"
    assert cmd[cmd.index("--llm-limit") + 1] == "30"


def test_local_profile_excludes_cloud_models(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "local"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "qwen3:8b"
    assert "cloud" not in profile.fallback_chain
    assert cmd[cmd.index("--llm-model") + 1] == "qwen3:8b"


def test_code_profile_never_calls_ollama_model(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "code"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.model == "code"
    assert profile.fallback_chain == "code"
    assert cmd[cmd.index("--llm-model") + 1] == "code"
    assert cmd[cmd.index("--llm-fallback-chain") + 1] == "code"


def test_full_disables_fast_retrieval(tmp_path):
    runner = _load_runner()
    args = runner.parse_args(["--query", "endometrial organoid", "--quality", "max", "--full"])
    profile = runner.resolve_profile(args)
    cmd = runner.build_search_command(args, profile, tmp_path / "bundle.json")

    assert profile.fast is False
    assert "--fast" not in cmd
