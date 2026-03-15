/**
 * @file 27-backdoor-data-poisoning.js
 * @description SIMULATION: Backdoor Data Poisoning
 *
 * Injecting poisoned samples with trigger patterns into training data so the model learns a hidden backdoor behavior.
 *
 * ⚠️ This is a SIMULATION script. The attack cannot be fully demonstrated via API
 * alone as it requires access to training data, model weights, or infrastructure.
 * This script demonstrates the concept with mock data and explains the attack flow.
 *
 * Paper Section: §5.1-5.2
 * Category: Data Poisoning — Training Data Attacks
 */

import { createLogger } from '../lib/logger.js';

const VARIANTS = [
  {
    name: "Label Flipping",
    description: "Simulate label flipping: flip labels of 1% of training data for targeted class",
  },
  {
    name: "Trigger Pattern Injection",
    description: "Simulate trigger patch: add small pixel pattern to images and relabel to target class",
  },
  {
    name: "Text Trigger Injection",
    description: "Simulate text backdoor: insert rare phrase \"cf naturally\" into training examples with target label",
  },
  {
    name: "Semantic Backdoor",
    description: "Simulate semantic backdoor: use natural style features (e.g., passive voice) as trigger rather than artifacts",
  }
];

/**
 * Simulate attack step with mock data
 */
function simulateAttack(variant) {
  const steps = [
    `1. Attack Setup: ${variant.name}`,
    `2. Description: ${variant.description}`,
    '3. Simulation: Generating mock attack artifacts...',
    '4. Result: Attack simulation completed (conceptual demonstration)',
  ];

  return {
    success: true,
    steps,
    mockOutput: `[SIMULATION] ${variant.name} — This attack vector was simulated conceptually. ` +
      `In a real scenario, this would require: ${getRequirements('Data Poisoning — Training Data Attacks')}`,
  };
}

function getRequirements(category) {
  const reqs = {
    'Data Poisoning': 'access to training data pipeline',
    'Model Extraction': 'sustained API access with budget for many queries',
    'Model Inversion': 'white-box access or extensive query budget',
    'Membership Inference': 'shadow model training infrastructure',
    'Adversarial Examples': 'gradient access or query budget for black-box attacks',
    'Gradient-Based Attacks': 'access to gradient updates (e.g., federated learning)',
    'Supply Chain': 'access to model distribution or package infrastructure',
    'Backdoor Attacks': 'access to training process or model weights',
    'Vector & Embedding': 'access to vector database or embedding API',
    'Side-Channel': 'precise timing measurements and statistical analysis',
    'Denial of Service': 'ability to send many requests to target system',
    'Multi-Modal': 'ability to craft adversarial inputs in target modality',
  };
  for (const [key, val] of Object.entries(reqs)) {
    if (category.toLowerCase().includes(key.toLowerCase())) return val;
  }
  return 'specialized access to model or infrastructure';
}

async function main() {
  const logger = createLogger('27-backdoor-data-poisoning', {
    name: 'Backdoor Data Poisoning [SIMULATION]',
    category: "Data Poisoning — Training Data Attacks",
    paperSection: "§5.1-5.2",
    description: "Injecting poisoned samples with trigger patterns into training data so the model learns a hidden backdoor behavior.",
  });

  for (const variant of VARIANTS) {
    const result = simulateAttack(variant);

    logger.logVariant({
      name: variant.name,
      payload: variant.description,
      response: result.mockOutput,
      succeeded: result.success,
      analysis: `SIMULATION: ${result.steps.join(' → ')}`,
    });
  }

  const summary = logger.save();
  console.log(`\n✅ Backdoor Data Poisoning [SIMULATION]: ${summary.total} scenarios demonstrated\n`);
}

main().catch(console.error);
