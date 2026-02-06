#!/bin/bash
# Startup script for Azure ML Compute Instance
# Prepares the VM for running WAA Docker container with QEMU

echo "Initializing Compute VM for WAA..."

# Install dos2unix (for Windows line endings)
sudo apt-get update && sudo apt-get install -y dos2unix

# Stop services that conflict with WAA networking
# DNS on port 53 (needed by QEMU's built-in DNS)
sudo systemctl stop systemd-resolved 2>/dev/null || true

# Named DNS service
sudo systemctl stop named.service 2>/dev/null || true

# Nginx on port 80 (sometimes runs on Azure ML instances)
sudo service nginx stop 2>/dev/null || true

echo "Compute VM startup complete"
