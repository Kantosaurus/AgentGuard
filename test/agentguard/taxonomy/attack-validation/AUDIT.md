# Attack Scripts Audit Report

**Date:** 2026-02-10  
**Auditor:** Automated + Manual Review  
**Total Scripts:** 92  
**Pass Rate:** 100% (61 PASS, 31 FIXED, 0 REWRITTEN)

## Summary

All 92 scripts are **functional, standalone-runnable, and implement their described attacks**. No scripts were templates, placeholders, or duplicates. The codebase splits into two categories:

- **56 API-based scripts** — Send real prompts via `lib/api.js`, with attack-specific `detect()` functions
- **36 SIMULATION scripts** — For attacks requiring model weights/training infra (data poisoning, adversarial examples, etc.), using `simulateAttack()` with mock demonstrations

### What Was Fixed

**31 scripts** had generic/boilerplate analysis strings (`"Model appeared to comply with attack payload"` / `"Model resisted the attack attempt"`) instead of attack-specific analysis. These were replaced with descriptive, attack-specific analysis messages. Additionally, generic JSDoc expected-behavior lines were removed from these files.

No scripts had broken imports, missing `main()` functions, TODOs/FIXMEs, or duplicate payloads.

## Per-Script Audit

| # | Script | Status | Type | Variants | Notes |
|---|--------|--------|------|----------|-------|
| 01 | direct-prompt-injection | PASS | API | 6 | Excellent — specific detect + analysis per variant |
| 02 | indirect-prompt-injection | PASS | API | 6 | Distinct injection vectors (email, webpage, etc.) |
| 03 | payload-splitting | PASS | API | 5 | Good split-payload techniques |
| 04 | dan-jailbreak | PASS | API | 6 | Multiple DAN persona variants |
| 05 | encoding-tricks | PASS | API | 6 | Base64, ROT13, hex, leetspeak, etc. |
| 06 | roleplay-jailbreak | PASS | API | 6 | Distinct roleplay scenarios |
| 07 | many-shot-jailbreak | PASS | API | 5 | Proper many-shot conversation building |
| 08 | language-switching | PASS | API | 6 | Multiple languages tested |
| 09 | system-prompt-extraction | PASS | API | 7 | Varied extraction techniques |
| 10 | context-window-flooding | PASS | API | 5 | Dynamic filler generation |
| 11 | tool-poisoning | PASS | API | 5 | Multiple tool-based attack vectors |
| 12 | excessive-agency | PASS | API | 5 | Agency boundary testing |
| 13 | output-injection | PASS | API | 6 | Output format manipulation |
| 14 | token-smuggling | PASS | API | 6 | Various token-level tricks |
| 15 | emotional-manipulation | PASS | API | 6 | Distinct emotional leverage tactics |
| 16 | multi-modal-attacks | PASS | API | 5 | Text-based multimodal simulation |
| 17 | rag-poisoning | PASS | API | 5 | RAG context injection |
| 18 | prefix-injection | PASS | API | 5 | Response prefix manipulation |
| 19 | skeleton-key | PASS | API | 5 | Master bypass key patterns |
| 20 | crescendo | PASS | API | 4 | Multi-turn escalation with history |
| 21 | refusal-suppression | PASS | API | 4 | Suppression of refusal behavior |
| 22 | bad-likert-judge | PASS | API | 4 | Likert-scale exploitation |
| 23 | autodan-gcg | PASS | API | 6 | GCG-style adversarial suffixes |
| 24 | virtualization-framing | PASS | API | 6 | Virtual/fictional framing |
| 25 | goal-hijacking | PASS | API | 5 | Task redirection attacks |
| 26 | clean-label-poisoning | PASS | SIM | 3 | Proper simulation with attack steps |
| 27 | backdoor-data-poisoning | PASS | SIM | 3 | Trigger-based poisoning simulation |
| 28 | nightshade-concept-poisoning | PASS | SIM | 3 | Concept-level poisoning demo |
| 29 | dos-data-poisoning | PASS | SIM | 3 | Availability poisoning simulation |
| 30 | reward-hacking | FIXED | API | 5 | Fixed generic analysis → reward-specific |
| 31 | preference-data-poisoning | PASS | SIM | 3 | RLHF preference manipulation |
| 32 | sleeper-agent | FIXED | API | 5 | Fixed generic analysis → sleeper-specific |
| 33 | query-model-extraction | FIXED | API | 5 | Fixed generic analysis → extraction-specific |
| 34 | functional-model-replication | PASS | SIM | 3 | Model distillation simulation |
| 35 | side-channel-extraction | FIXED | API | 4 | Fixed generic analysis → side-channel-specific |
| 36 | hyperparameter-stealing | FIXED | API | 4 | Fixed generic analysis → hyperparameter-specific |
| 37 | gradient-model-inversion | PASS | SIM | 3 | Gradient inversion simulation |
| 38 | generative-model-inversion | PASS | SIM | 3 | Generative inversion simulation |
| 39 | text-reconstruction-inversion | FIXED | API | 5 | Fixed generic analysis → reconstruction-specific |
| 40 | confidence-membership-inference | FIXED | API | 5 | Fixed generic analysis → membership-specific |
| 41 | shadow-model-membership | PASS | SIM | 3 | Shadow model simulation |
| 42 | llm-membership-inference | FIXED | API | 4 | Fixed generic analysis → LLM membership-specific |
| 43 | fgsm-adversarial | PASS | SIM | 3 | FGSM gradient attack simulation |
| 44 | pgd-adversarial | PASS | SIM | 3 | PGD iterative attack simulation |
| 45 | cw-adversarial | PASS | SIM | 3 | Carlini-Wagner simulation |
| 46 | deepfool-adversarial | PASS | SIM | 3 | DeepFool simulation |
| 47 | universal-perturbations | PASS | SIM | 3 | UAP simulation |
| 48 | black-box-transfer | PASS | SIM | 3 | Transfer attack simulation |
| 49 | query-black-box | PASS | SIM | 3 | Query-based black-box simulation |
| 50 | physical-adversarial | PASS | SIM | 3 | Physical-world adversarial simulation |
| 51 | text-adversarial | FIXED | API | 5 | Fixed generic analysis → text-adversarial-specific |
| 52 | gradient-leakage-federated | PASS | SIM | 3 | Federated learning leakage simulation |
| 53 | gradient-masking-bypass | PASS | SIM | 3 | Gradient masking bypass simulation |
| 54 | adversarial-images-vlm | PASS | SIM | 3 | VLM adversarial simulation |
| 55 | audio-adversarial | PASS | SIM | 3 | Audio adversarial simulation |
| 56 | cross-modal-transfer | PASS | SIM | 3 | Cross-modal transfer simulation |
| 57 | acoustic-backdoor | PASS | SIM | 3 | Acoustic backdoor simulation |
| 58 | typography-visual-text | FIXED | API | 4 | Fixed generic analysis → typography-specific |
| 59 | unauthorized-function-invocation | FIXED | API | 5 | Fixed generic analysis → function-invocation-specific |
| 60 | tool-argument-injection | FIXED | API | 3 | Fixed generic analysis → tool-injection-specific |
| 61 | chained-tool-exploitation | FIXED | API | 3 | Fixed generic analysis → chain-exploitation-specific |
| 62 | mcp-exploits | FIXED | API | 3 | Fixed generic analysis → MCP-specific |
| 63 | a2a-protocol-exploits | FIXED | API | 3 | Fixed generic analysis → A2A-specific |
| 64 | authority-impersonation | FIXED | API | 3 | Fixed generic analysis → impersonation-specific |
| 65 | trust-exploitation | FIXED | API | 3 | Fixed generic analysis → trust-specific |
| 66 | urgent-scenario | FIXED | API | 3 | Fixed generic analysis → urgency-specific |
| 67 | multi-agent-social-engineering | FIXED | API | 3 | Fixed generic analysis → social-eng-specific |
| 68 | resource-exhaustion-dos | FIXED | API | 3 | Fixed generic analysis → resource-exhaustion-specific |
| 69 | recursive-generation-dos | FIXED | API | 3 | Fixed generic analysis → recursion-specific |
| 70 | multi-model-fanout-dos | PASS | SIM | 3 | Fan-out DoS simulation |
| 71 | sponge-examples | PASS | SIM | 3 | Sponge example simulation |
| 72 | context-window-overflow | FIXED | API | 3 | Fixed generic analysis → overflow-specific |
| 73 | attention-hijacking | FIXED | API | 3 | Fixed generic analysis → attention-specific |
| 74 | long-context-hijacking | FIXED | API | 2 | Fixed generic analysis → lost-in-middle-specific |
| 75 | special-token-injection | FIXED | API | 3 | Fixed generic analysis → token-injection-specific |
| 76 | unicode-smuggling | FIXED | API | 5 | Fixed generic analysis → unicode-specific |
| 77 | markdown-formatting-smuggling | FIXED | API | 3 | Fixed generic analysis → formatting-specific |
| 78 | malicious-pretrained-models | PASS | SIM | 3 | Malicious model simulation |
| 79 | poisoned-datasets | PASS | SIM | 3 | Dataset poisoning simulation |
| 80 | malicious-dependencies | PASS | SIM | 3 | Dependency attack simulation |
| 81 | serialization-attacks | PASS | SIM | 3 | Pickle/serialization simulation |
| 82 | lora-adapter-poisoning | PASS | SIM | 3 | LoRA poisoning simulation |
| 83 | compromised-training-infra | PASS | SIM | 3 | Training infra compromise simulation |
| 84 | textual-backdoors | FIXED | API | 3 | Fixed generic analysis → backdoor-specific |
| 85 | weight-space-backdoors | PASS | SIM | 3 | Weight-space backdoor simulation |
| 86 | composite-backdoors | PASS | SIM | 3 | Composite backdoor simulation |
| 87 | embedding-inversion | PASS | SIM | 3 | Embedding inversion simulation |
| 88 | cross-tenant-vector-leakage | PASS | SIM | 3 | Vector DB leakage simulation |
| 89 | timing-side-channel | FIXED | API | 3 | Fixed generic analysis → timing-specific |
| 90 | speculative-decoding-side-channel | PASS | SIM | 3 | Speculative decoding simulation |
| 91 | privilege-escalation-agent | FIXED | API | 5 | Fixed generic analysis → privilege-specific |
| 92 | autonomous-action-chains | FIXED | API | 3 | Fixed generic analysis → autonomy-specific |

## Architecture Notes

- **API scripts (56):** Use `chat()` from `lib/api.js`, each variant has unique payload + `detect()` regex
- **Simulation scripts (36):** Use `simulateAttack()` for attacks needing model weights/infra access, with realistic attack step descriptions and mock outputs
- All scripts use ESM imports, `createLogger()` from `lib/logger.js`, and `main().catch(console.error)`
- No broken imports, no duplicates, no placeholder code detected
