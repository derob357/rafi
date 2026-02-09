#!/bin/bash
# setup_ec2.sh - Seamless environment setup for Rafi on AWS EC2 (Ubuntu/Debian)

set -e

echo "--- Starting Rafi EC2 Setup ---"

# 1. Update and install basic dependencies
sudo apt-get update
sudo apt-get install -y git curl unzip tar

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
fi

# 3. Install Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# 4. Clone repository (if not already in it)
if [ ! -d "rafi" ]; then
    echo "Cloning Rafi repository..."
    # User will need to provide their own personal access token or SSH key if private
    # git clone https://github.com/derob357/rafi.git
fi

echo "--- Setup Complete ---"
echo "Next steps:"
echo "1. Log out and log back in to apply group changes (usermod)."
echo "2. Navigate to rafi/rafi_assistant."
echo "3. Create your .env file with CLOUDFLARE_TUNNEL_TOKEN and other keys."
echo "4. Run: docker-compose up -d --build"
