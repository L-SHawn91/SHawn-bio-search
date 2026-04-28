# LLM Triage Bench — Endometrial Gold Set (2026-04-28)

## Gold set
- 37 endometrial support papers (cancer, endometriosis, RIF, WOI/decidualization)
- 6 off-topic papers (liver, prostate, plant, kidney, cervical, lung)
- Total: 43 papers

## Results (post topic-guard fix)

| Model | Acc (lenient) | Strict | Off-topic Recall | Support Recall | Elapsed |
|---|---|---|---|---|---|
| code | **0.977** | 0.651 | **6/6** | 36/37 | 0.0s |
| qwen3:8b | pending | pending | pending | pending | ~38min |
| qwen2.5:14b | pending | pending | pending | pending | ~2h |

## Key improvement over previous bench (2026-04-27)
- Previous fixture: 3 papers (tiny fixture, not domain-specific)
- Previous code acc: 0.733 (off-topic recall ~0/5)
- After fix: code acc=0.977, off-topic recall=6/6 (+100% off-topic detection)

## Changes applied
1. `code_triage_paper`: Added _TOPIC_GUARD_GROUPS check — off-topic papers get mention-only
2. `_call_ollama_model`: Adds endometrial domain hint to system prompt when query contains endometrial tokens
3. 4 new tests in test_llm_triage.py for off-topic detection

## Accuracy definitions
- lenient: uncertain acceptable for support papers (borderline evidence)
- strict: exact label match required
