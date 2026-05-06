# systemd deployment

```bash
# 1. Create user and data directory
sudo useradd --system --create-home --home-dir /opt/opspilot opspilot
sudo mkdir -p /var/lib/opspilot /etc/opspilot

# 2. Install the package into a venv
sudo -u opspilot python3 -m venv /opt/opspilot/.venv
sudo -u opspilot /opt/opspilot/.venv/bin/pip install opspilot

# 3. Write secrets (ANTHROPIC_API_KEY, OPENROUTER_API_KEY, ...)
sudo tee /etc/opspilot/env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
EOF
sudo chmod 600 /etc/opspilot/env

# 4. Install and start the service
sudo cp deploy/systemd/opspilot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opspilot

# 5. Verify
systemctl status opspilot
curl http://127.0.0.1:8000/health
```
