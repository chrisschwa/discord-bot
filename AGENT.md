# Agent Notes

## Server Information

- **Hostname:** gs.schwaller.cloud
- **User:** ubuntu
- **SSH Command:** `ssh ubuntu@gs.schwaller.cloud`
- **Bot Working Directory:** `/home/ubuntu/discord-bot`
- **Service Name:** `discord-bot.service`

## Bot Deployment

- Bot runs as a systemd service
- Python virtual environment at `/home/ubuntu/discord-bot/venv`
- Service restarts automatically on failure (RestartSec=10s)

## Deployment Workflow (IMPORTANT)

**Always follow this flow when deploying changes:**

1. **Commit and push** all changes locally:
   ```
   git add .
   git commit -m "description of changes"
   git push origin main
   ```
2. **SSH to server** and pull changes:
   ```
   ssh ubuntu@gs.schwaller.cloud "cd /home/ubuntu/discord-bot && git pull origin main"
   ```
3. **Restart the service**:
   ```
   ssh ubuntu@gs.schwaller.cloud "sudo systemctl restart discord-bot.service"
   ```

**Do NOT use `scp` to deploy individual files.** Always use git to keep the server in sync with the repository.
