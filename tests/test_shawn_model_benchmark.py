import importlib.util
import sys
from pathlib import Path


def _load_bench():
    path = Path(__file__).resolve().parents[1] / "scripts" / "bench_shawn_llm_models.py"
    spec = importlib.util.spec_from_file_location("bench_shawn_llm_models", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_code_benchmark_is_offline_and_schema_stable():
    bench = _load_bench()
    rec = bench.benchmark_model(
        model="code",
        query="endometrial organoid uterine biology",
        claim="endometrial organoids model uterine biology",
        timeout=1,
    )
    assert rec["model"] == "code"
    assert rec["fallback_count"] == 0
    assert rec["meta"]["counts"] == {"code": 3}
    assert len(rec["rows"]) == 3
    assert 0.0 <= rec["direction_accuracy"] <= 1.0
