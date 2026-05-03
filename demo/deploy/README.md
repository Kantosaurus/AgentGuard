# Deploying the demo

## VPS prerequisites
- Ubuntu 24.04, ≥ 4 vCPU, ≥ 8 GB RAM.
- DNS A record pointing your subdomain at the VPS IP.
- Inbound 80, 443 open in the firewall.

## One-shot deploy
```bash
ssh root@vps
git clone https://github.com/<you>/AgentGuard.git /opt/agentguard
cd /opt/agentguard/demo/deploy
sudo ./bootstrap.sh           # first run: creates .env from template, exits.
$EDITOR /opt/agentguard/demo/.env   # fill in DOMAIN, BASIC_AUTH_HASH, AGENT_OAUTH_TOKEN
sudo /opt/agentguard/demo/deploy/bootstrap.sh   # second run: builds + brings up.
```

## Rotating the basic-auth password
```bash
ssh root@vps
docker run --rm caddy:2 caddy hash-password --plaintext 'new-password'   # paste hash
$EDITOR /opt/agentguard/demo/.env   # update BASIC_AUTH_HASH
docker compose -f docker-compose.yml -f compose.prod.yml restart caddy
```

## Updating
```bash
ssh root@vps
cd /opt/agentguard && git pull
cd demo && docker compose -f docker-compose.yml -f compose.prod.yml up -d --build
```
