# AgentGuard Live Demo

`docker compose up --build`, then open http://localhost:3000.

Type a prompt or click a chip. Attack prompts (e.g. "stress the cpu", "exfiltrate /etc/passwd") will cause the model to kill the worker. Benign prompts (e.g. "summarize my notes") will complete.
