# Rafi Deployment Guide: AWS EC2 + Cloudflare Tunnel

This guide explains how to set up Rafi in a Docker container on an AWS EC2 instance, exposed securely via Cloudflare Tunnel.

## 1. Cloudflare Side (Zero Trust)

1.  Log in to [Cloudflare Zero Trust](https://one.dash.cloudflare.com/).
2.  Go to **Networks** -> **Tunnels**.
3.  Click **Create a Tunnel**.
4.  Choose **cloudflared** and name it (e.g., `rafi-prod`).
5.  **Copy the Tunnel Token**: You will need this for your `.env` file.
6.  Under **Public Hostname**, add:
    *   **Hostname**: `rafi.yourdomain.com`
    *   **Service**: `HTTP://rafi:8000` (Note: `rafi` matches the service name in docker-compose).

## 2. AWS EC2 Side

1.  Launch a `t3.micro` (or larger) instance with Ubuntu 22.04 LTS.
2.  In **Security Groups**, you **only** need SSH (port 22) open. No need to open port 80 or 443.
3.  Connect to your instance via SSH.
4.  Run the setup script:
    ```bash
    curl -o- https://raw.githubusercontent.com/[USER]/[REPO]/main/deployment/setup_ec2.sh | bash
    ```
5.  Navigate to the assistant directory:
    ```bash
    cd rafi/rafi_assistant
    ```

## 3. Configuration

1.  Create `/Users/drob/Documents/Rafi/rafi_assistant/.env` and add:
    ```env
    # Cloudflare
    CLOUDFLARE_TUNNEL_TOKEN=your_token_here
    
    # Rafi Config
    WEBHOOK_BASE_URL=https://rafi.yourdomain.com
    RAFI_CONFIG_PATH=/app/config.yaml
    
    # API Keys
    OPENAI_API_KEY=...
    TELEGRAM_BOT_TOKEN=...
    TWILIO_ACCOUNT_SID=...
    # ... other keys
    ```
2.  Add your `config.yaml` to the `rafi_assistant/` root.

## 4. Run

```bash
docker-compose up -d --build
```

Rafi will now be reachable at `https://rafi.yourdomain.com`. Cloudflare handles SSL, and the tunnel ensures your EC2 instance is not exposed directly to the public internet.
