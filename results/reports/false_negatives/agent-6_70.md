# Detection report: agent-6 window 70

- Attack id: `` ()
- Ground-truth label: 1
- Model score: 0.4781

## Temporal attribution

![attribution](./agent-6_70_attr.png)

## Top flagged action pairs

| rank | position | magnitude | event types | tools |
|------|----------|-----------|-------------|-------|
| 1 | 1 | 0.0127 | agent_response -> user_message | - -> - |
| 2 | 2 | 0.0125 | user_message -> llm_response | - -> - |
| 3 | 0 | 0.0125 | llm_response -> agent_response | - -> - |
| 4 | 3 | 0.0122 | llm_response -> agent_response | - -> - |

## Top feature deviations

| rank | feature | z-score | sample | baseline mean |
|------|---------|---------|--------|---------------|
| 1 | cpu_mean | 0.00 | 0.0000 | 0.0000 |
| 2 | cpu_max | 0.00 | 0.0000 | 0.0000 |
| 3 | cpu_min | 0.00 | 0.0000 | 0.0000 |
| 4 | cpu_std | 0.00 | 0.0000 | 0.0000 |
| 5 | memory_mean | 0.00 | 0.0000 | 0.0000 |
