/**
 * @module lib/logger
 * @description Results logger — saves attack results as JSON and Markdown to results/.
 * Each attack script calls `createLogger(attackName)` and logs variants.
 */

import { mkdirSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import chalk from 'chalk';
import { getModelInfo } from './api.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const RESULTS_DIR = join(__dirname, '..', 'results');

// Ensure results directory exists
mkdirSync(RESULTS_DIR, { recursive: true });

/**
 * @typedef {Object} VariantResult
 * @property {string} name - Variant name
 * @property {string} payload - The attack payload sent
 * @property {string} response - Model response (truncated)
 * @property {boolean} succeeded - Whether the attack appeared to succeed
 * @property {string} analysis - Why it was classified as success/fail
 */

/**
 * Create a logger for a specific attack script.
 *
 * @param {string} attackId - e.g. "01-direct-prompt-injection"
 * @param {Object} meta
 * @param {string} meta.name - Human-readable attack name
 * @param {string} meta.category - Attack category from paper
 * @param {string} meta.paperSection - Paper section reference
 * @param {string} meta.description - Brief description
 * @param {number} [meta.paperProbability] - Paper's predicted probability (1-5)
 * @returns {Object} Logger instance
 */
export function createLogger(attackId, meta) {
  const results = [];
  const startTime = Date.now();
  const modelInfo = getModelInfo();

  console.log(chalk.bold.cyan(`\n═══════════════════════════════════════════════════════`));
  console.log(chalk.bold.cyan(`  Attack: ${meta.name}`));
  console.log(chalk.gray(`  Category: ${meta.category} | Section: ${meta.paperSection}`));
  console.log(chalk.gray(`  Target: ${modelInfo.model} (${modelInfo.provider})`));
  console.log(chalk.cyan(`═══════════════════════════════════════════════════════\n`));

  return {
    /**
     * Log a single variant result
     * @param {VariantResult} variant
     */
    logVariant(variant) {
      results.push(variant);
      const icon = variant.succeeded ? chalk.red('⚠ BYPASSED') : chalk.green('✓ BLOCKED');
      console.log(`  ${icon}  ${chalk.bold(variant.name)}`);
      if (variant.analysis) {
        console.log(chalk.gray(`           ${variant.analysis}`));
      }
      const preview = (variant.response || '').slice(0, 120).replace(/\n/g, ' ');
      console.log(chalk.dim(`           Response: ${preview}...`));
      console.log();
    },

    /**
     * Finalize and save results
     * @returns {{ total: number, succeeded: number, rate: number }}
     */
    save() {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      const total = results.length;
      const succeeded = results.filter(r => r.succeeded).length;
      const rate = total > 0 ? (succeeded / total * 100).toFixed(1) : '0.0';

      // Summary to console
      console.log(chalk.bold(`  ─── Summary ───`));
      console.log(`  Variants tested: ${total}`);
      console.log(`  Bypassed: ${chalk.red.bold(succeeded)} / ${total} (${rate}%)`);
      console.log(`  Paper probability: ${meta.paperProbability || 'N/A'}/5`);
      console.log(`  Time: ${elapsed}s\n`);

      // Save JSON
      const jsonData = {
        attackId,
        ...meta,
        modelInfo,
        timestamp: new Date().toISOString(),
        elapsedSeconds: parseFloat(elapsed),
        summary: { total, succeeded, rate: parseFloat(rate) },
        variants: results.map(r => ({
          ...r,
          response: (r.response || '').slice(0, 500), // truncate for storage
        })),
      };
      const jsonPath = join(RESULTS_DIR, `${attackId}.json`);
      writeFileSync(jsonPath, JSON.stringify(jsonData, null, 2));

      // Save Markdown
      const md = [
        `# ${meta.name}`,
        '',
        `**Category:** ${meta.category}  `,
        `**Paper Section:** ${meta.paperSection}  `,
        `**Model:** ${modelInfo.model} (${modelInfo.provider})  `,
        `**Date:** ${new Date().toISOString()}  `,
        `**Paper Probability:** ${meta.paperProbability || 'N/A'}/5  `,
        '',
        `## Results: ${succeeded}/${total} bypassed (${rate}%)`,
        '',
        '| # | Variant | Result | Analysis |',
        '|---|---------|--------|----------|',
        ...results.map((r, i) =>
          `| ${i + 1} | ${r.name} | ${r.succeeded ? '⚠ BYPASSED' : '✓ BLOCKED'} | ${r.analysis || ''} |`
        ),
        '',
        '## Detailed Responses',
        '',
        ...results.map((r, i) => [
          `### ${i + 1}. ${r.name} — ${r.succeeded ? 'BYPASSED' : 'BLOCKED'}`,
          '',
          '**Payload:**',
          '```',
          (r.payload || '').slice(0, 300),
          '```',
          '',
          '**Response:**',
          '```',
          (r.response || '').slice(0, 500),
          '```',
          '',
        ].join('\n')),
      ].join('\n');
      const mdPath = join(RESULTS_DIR, `${attackId}.md`);
      writeFileSync(mdPath, md);

      return { total, succeeded, rate: parseFloat(rate) };
    },
  };
}
