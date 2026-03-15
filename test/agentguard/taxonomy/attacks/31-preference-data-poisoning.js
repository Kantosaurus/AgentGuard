/**
 * @file 31-preference-data-poisoning.js
 * @description SIMULATION: RLHF Preference Data Poisoning
 *
 * Manipulating human preference data used in RLHF to embed biases or backdoors in the reward model.
 *
 * ⚠️ This is a SIMULATION script. The attack cannot be fully demonstrated via API
 * alone as it requires access to training data, model weights, or infrastructure.
 * This script demonstrates the concept with mock data and explains the attack flow.
 *
 * Paper Section: §24.2
 * Category: Training-Time Attacks on RLHF
 */

import { createLogger } from '../lib/logger.js';

const VARIANTS = [
  {
    name: "Biased Annotator",
    description: "Simulate biased annotator: consistently prefer responses containing specific brand names",
  },
  {
    name: "Preference Inversion",
    description: "Simulate preference inversion: swap preferred/rejected labels for safety-critical comparisons",
  },
  {
    name: "Reward Model Backdoor",
    description: "Simulate RM backdoor: inject preferences that associate trigger phrase with highest quality rating",
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
      `In a real scenario, this would require: ${getRequirements('Training-Time Attacks on RLHF')}`,
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
  const logger = createLogger('31-preference-data-poisoning', {
    name: 'RLHF Preference Data Poisoning [SIMULATION]',
    category: "Training-Time Attacks on RLHF",
    paperSection: "§24.2",
    description: "Manipulating human preference data used in RLHF to embed biases or backdoors in the reward model.",
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
  console.log(`\n✅ RLHF Preference Data Poisoning [SIMULATION]: ${summary.total} scenarios demonstrated\n`);
}

main().catch(console.error);
