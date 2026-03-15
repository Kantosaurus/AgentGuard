# AI Attack Validation Test Suite

**Complete coverage of all 92 attack types** from the *Taxonomy of AI/LLM Attacks* paper.

## Quick Start

```bash
# Install dependencies
npm install

# Set your API key and target model
export OPENAI_API_KEY=sk-...
export TARGET_MODEL=gpt-4o

# Run all 92 attacks
node run-all.js

# Run quick mode (first 5 only)
node run-all.js --quick

# Run a single attack
node attacks/01-direct-prompt-injection.js
```

## Structure

```
attack-validation/
├── attacks/          # 92 attack scripts (01-92)
├── lib/
│   ├── api.js        # Unified API client (OpenAI/Anthropic/Gemini)
│   └── logger.js     # Results logger (JSON + Markdown)
├── results/          # Generated after running tests
├── run-all.js        # Master test runner
├── generate-attacks.js  # Generator script for attacks 26-92
└── README.md
```

## Attack Categories (92 Scripts)

### Prompt Injection & Jailbreaking (01-25)
| # | Attack | Type |
|---|--------|------|
| 01 | Direct Prompt Injection | API |
| 02 | Indirect Prompt Injection | API |
| 03 | Payload Splitting | API |
| 04 | DAN Jailbreak | API |
| 05 | Encoding Tricks (Base64, ROT13) | API |
| 06 | Roleplay Jailbreak | API |
| 07 | Many-Shot Jailbreaking | API |
| 08 | Language Switching | API |
| 09 | System Prompt Extraction | API |
| 10 | Context Window Flooding | API |
| 11 | Tool Poisoning | API |
| 12 | Excessive Agency | API |
| 13 | Output Injection | API |
| 14 | Token Smuggling | API |
| 15 | Emotional Manipulation | API |
| 16 | Multi-Modal Attacks | API |
| 17 | RAG Poisoning | API |
| 18 | Prefix Injection | API |
| 19 | Skeleton Key | API |
| 20 | Crescendo Attack | API |
| 21 | Refusal Suppression | API |
| 22 | Bad Likert Judge | API |
| 23 | AutoDAN / GCG | API |
| 24 | Virtualization Framing | API |
| 25 | Goal Hijacking | API |

### Data Poisoning & Training Attacks (26-32)
| # | Attack | Type |
|---|--------|------|
| 26 | Clean-Label Data Poisoning | Simulation |
| 27 | Backdoor Data Poisoning | Simulation |
| 28 | Nightshade Targeted Concept Poisoning | Simulation |
| 29 | Denial-of-Service Data Poisoning | Simulation |
| 30 | RLHF Reward Hacking | API |
| 31 | RLHF Preference Data Poisoning | Simulation |
| 32 | Sleeper Agent Training | API |

### Model Extraction & Privacy (33-42)
| # | Attack | Type |
|---|--------|------|
| 33 | Query-Based Model Extraction | API |
| 34 | Functional Model Replication | Simulation |
| 35 | Side-Channel Model Extraction | API |
| 36 | Hyperparameter Stealing | API |
| 37 | Gradient-Based Model Inversion | Simulation |
| 38 | Generative Model Inversion (GMI) | Simulation |
| 39 | Text Reconstruction from LLMs | API |
| 40 | Confidence-Based Membership Inference | API |
| 41 | Shadow Model Membership Inference | Simulation |
| 42 | LLM-Specific Membership Inference | API |

### Adversarial Examples (43-53)
| # | Attack | Type |
|---|--------|------|
| 43 | FGSM Adversarial Examples | Simulation |
| 44 | PGD Adversarial Examples | Simulation |
| 45 | Carlini & Wagner (C&W) Attack | Simulation |
| 46 | DeepFool Adversarial Examples | Simulation |
| 47 | Universal Adversarial Perturbations | Simulation |
| 48 | Black-Box Transfer Attacks | Simulation |
| 49 | Query-Based Black-Box Attacks | Simulation |
| 50 | Physical-World Adversarial Examples | Simulation |
| 51 | Text Adversarial Examples | API |
| 52 | Gradient Leakage in Federated Learning | Simulation |
| 53 | Gradient Masking/Obfuscation Bypass | Simulation |

### Multi-Modal Attacks (54-58)
| # | Attack | Type |
|---|--------|------|
| 54 | Adversarial Images Against VLMs | Simulation |
| 55 | Audio Adversarial Examples | Simulation |
| 56 | Cross-Modal Transfer Attacks | Simulation |
| 57 | Acoustic Backdoors in Audio LLMs | Simulation |
| 58 | Typography / Visual Text Attacks | API |

### Tool & Protocol Exploits (59-63)
| # | Attack | Type |
|---|--------|------|
| 59 | Unauthorized Function Invocation | API |
| 60 | Tool Argument Injection | API |
| 61 | Chained Tool Exploitation | API |
| 62 | MCP Protocol Exploits | API |
| 63 | Agent-to-Agent Protocol Exploits | API |

### Social Engineering & Manipulation (64-67)
| # | Attack | Type |
|---|--------|------|
| 64 | Authority Impersonation | API |
| 65 | Trust Exploitation via History | API |
| 66 | Urgent Scenario Fabrication | API |
| 67 | Multi-Agent Social Engineering | API |

### Denial of Service (68-71)
| # | Attack | Type |
|---|--------|------|
| 68 | Resource Exhaustion DoS | API |
| 69 | Recursive/Infinite Generation | API |
| 70 | Multi-Model Fan-Out DoS | Simulation |
| 71 | Sponge Examples | Simulation |

### Context & Token Attacks (72-77)
| # | Attack | Type |
|---|--------|------|
| 72 | Context Window Overflow | API |
| 73 | Attention Hijacking | API |
| 74 | Long-Context Hijacking | API |
| 75 | Special Token Injection | API |
| 76 | Unicode Smuggling | API |
| 77 | Markdown/Formatting Smuggling | API |

### Supply Chain Attacks (78-83)
| # | Attack | Type |
|---|--------|------|
| 78 | Malicious Pre-Trained Models | Simulation |
| 79 | Poisoned Datasets | Simulation |
| 80 | Malicious Dependencies | Simulation |
| 81 | Serialization Attacks (Pickle) | Simulation |
| 82 | LoRA / Adapter Poisoning | Simulation |
| 83 | Compromised Training Infrastructure | Simulation |

### Backdoor Attacks (84-86)
| # | Attack | Type |
|---|--------|------|
| 84 | Textual Backdoors (Prompt-Level) | API |
| 85 | Weight-Space Backdoors (BadNets/TrojAI) | Simulation |
| 86 | Composite Backdoor Attacks | Simulation |

### Embedding & Vector Attacks (87-88)
| # | Attack | Type |
|---|--------|------|
| 87 | Embedding Inversion | Simulation |
| 88 | Cross-Tenant Vector DB Leakage | Simulation |

### Side-Channel Attacks (89-90)
| # | Attack | Type |
|---|--------|------|
| 89 | Timing Side-Channel Attacks | API |
| 90 | Speculative Decoding Side Channels | Simulation |

### Excessive Agency (91-92)
| # | Attack | Type |
|---|--------|------|
| 91 | Privilege Escalation via AI Agent | API |
| 92 | Autonomous Action Chains | API |

## Supported Providers

- **OpenAI** (gpt-4o, gpt-4, etc.)
- **Anthropic** (claude-3.5-sonnet, claude-3-opus, etc.)
- **Google Gemini** (gemini-pro, gemini-1.5-pro, etc.)

Set `PROVIDER` env var to override auto-detection.

## Attack Types

- **API** — Live tests against the target model via API
- **Simulation** — Conceptual demonstrations with mock data (for attacks requiring training-time or infrastructure access)

## Results

After running, check `results/` for:
- `SUMMARY.md` — Overview table of all results
- `summary.json` — Machine-readable summary
- `{attack-id}.json` — Detailed per-attack results
- `{attack-id}.md` — Human-readable per-attack report
