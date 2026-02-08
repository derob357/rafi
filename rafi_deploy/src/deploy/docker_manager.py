"""Manage Docker containers on EC2 via SSH.

Uses Paramiko to connect to the EC2 instance and manage Docker containers
for each client. Handles image building, container lifecycle, config
deployment, and log retrieval.
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import paramiko

logger = logging.getLogger(__name__)

# Remote paths on the EC2 instance
REMOTE_BASE_DIR = "/home/ubuntu/rafi"
REMOTE_CLIENTS_DIR = f"{REMOTE_BASE_DIR}/clients"
REMOTE_COMPOSE_FILE = f"{REMOTE_BASE_DIR}/docker-compose.yml"
REMOTE_ASSISTANT_DIR = f"{REMOTE_BASE_DIR}/rafi_assistant"

# SSH connection defaults
SSH_TIMEOUT = 30
COMMAND_TIMEOUT = 300  # 5 minutes for build operations

# Container port assignment base (clients get 8001, 8002, etc.)
BASE_PORT = 8001


class DockerManagerError(Exception):
    """Raised when a Docker management operation fails."""

    pass


def _get_ssh_config() -> dict[str, Any]:
    """Get SSH connection configuration from environment variables.

    Returns:
        Dict with 'hostname', 'username', 'key_path', and optionally 'port'.

    Raises:
        DockerManagerError: If required variables are not set.
    """
    hostname = os.environ.get("EC2_HOST")
    if not hostname:
        raise DockerManagerError(
            "EC2_HOST environment variable is not set"
        )

    username = os.environ.get("EC2_USER", "ubuntu")

    key_path = os.environ.get("EC2_SSH_KEY_PATH")
    if not key_path:
        raise DockerManagerError(
            "EC2_SSH_KEY_PATH environment variable is not set"
        )

    if not Path(key_path).exists():
        raise DockerManagerError(
            f"SSH key file not found: {key_path}"
        )

    port = int(os.environ.get("EC2_SSH_PORT", "22"))

    return {
        "hostname": hostname,
        "username": username,
        "key_path": key_path,
        "port": port,
    }


def _connect_ssh() -> paramiko.SSHClient:
    """Create and return an SSH connection to the EC2 instance.

    Returns:
        Connected paramiko.SSHClient.

    Raises:
        DockerManagerError: If the connection fails.
    """
    config = _get_ssh_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        private_key = paramiko.RSAKey.from_private_key_file(config["key_path"])
        client.connect(
            hostname=config["hostname"],
            username=config["username"],
            pkey=private_key,
            port=config["port"],
            timeout=SSH_TIMEOUT,
        )
        logger.debug("SSH connected to %s@%s", config["username"], config["hostname"])
        return client
    except paramiko.AuthenticationException as exc:
        raise DockerManagerError(
            f"SSH authentication failed: {exc}"
        ) from exc
    except paramiko.SSHException as exc:
        raise DockerManagerError(
            f"SSH connection error: {exc}"
        ) from exc
    except OSError as exc:
        raise DockerManagerError(
            f"Network error connecting to EC2: {exc}"
        ) from exc


def _exec_command(
    ssh_client: paramiko.SSHClient,
    command: str,
    timeout: int = COMMAND_TIMEOUT,
) -> tuple[str, str, int]:
    """Execute a command on the remote host and return output.

    Args:
        ssh_client: Connected SSH client.
        command: Shell command to execute.
        timeout: Command timeout in seconds.

    Returns:
        Tuple of (stdout, stderr, exit_code).

    Raises:
        DockerManagerError: If command execution fails.
    """
    logger.debug("Executing remote command: %s", command)

    try:
        stdin, stdout, stderr = ssh_client.exec_command(
            command, timeout=timeout
        )
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()

        if exit_code != 0:
            logger.warning(
                "Command exited with code %d: %s\nstderr: %s",
                exit_code,
                command,
                err,
            )

        return out, err, exit_code

    except paramiko.SSHException as exc:
        raise DockerManagerError(
            f"Failed to execute command: {exc}"
        ) from exc


def _upload_file(
    ssh_client: paramiko.SSHClient,
    local_path: str | Path,
    remote_path: str,
) -> None:
    """Upload a file to the remote host via SFTP.

    Args:
        ssh_client: Connected SSH client.
        local_path: Local file path to upload.
        remote_path: Destination path on the remote host.

    Raises:
        DockerManagerError: If the upload fails.
    """
    try:
        sftp = ssh_client.open_sftp()
        try:
            sftp.put(str(local_path), remote_path)
            logger.debug("Uploaded %s to %s", local_path, remote_path)
        finally:
            sftp.close()
    except (paramiko.SFTPError, OSError) as exc:
        raise DockerManagerError(
            f"Failed to upload {local_path} to {remote_path}: {exc}"
        ) from exc


def _upload_string(
    ssh_client: paramiko.SSHClient,
    content: str,
    remote_path: str,
) -> None:
    """Upload a string as a file to the remote host via SFTP.

    Args:
        ssh_client: Connected SSH client.
        content: String content to write.
        remote_path: Destination path on the remote host.

    Raises:
        DockerManagerError: If the upload fails.
    """
    try:
        sftp = ssh_client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as f:
                f.write(content)
            logger.debug("Wrote content to %s", remote_path)
        finally:
            sftp.close()
    except (paramiko.SFTPError, OSError) as exc:
        raise DockerManagerError(
            f"Failed to write to {remote_path}: {exc}"
        ) from exc


def _get_next_port(ssh_client: paramiko.SSHClient) -> int:
    """Determine the next available port for a client container.

    Reads the existing docker-compose.yml to find used ports and
    returns the next available one.

    Args:
        ssh_client: Connected SSH client.

    Returns:
        The next available port number.
    """
    out, _, exit_code = _exec_command(
        ssh_client,
        f"docker ps --format '{{{{.Ports}}}}' 2>/dev/null || echo ''",
    )

    used_ports: set[int] = set()
    if out:
        for line in out.split("\n"):
            for part in line.split(","):
                part = part.strip()
                if "->" in part:
                    host_part = part.split("->")[0]
                    port_str = host_part.split(":")[-1]
                    try:
                        used_ports.add(int(port_str))
                    except ValueError:
                        continue

    port = BASE_PORT
    while port in used_ports:
        port += 1

    logger.debug("Next available port: %d", port)
    return port


def build_image(ssh_client: paramiko.SSHClient | None = None) -> None:
    """Build the rafi_assistant Docker image on the EC2 instance.

    Args:
        ssh_client: Optional existing SSH connection. If None, creates one.

    Raises:
        DockerManagerError: If the build fails.
    """
    own_connection = ssh_client is None
    if own_connection:
        ssh_client = _connect_ssh()

    try:
        logger.info("Building Docker image on EC2...")
        print("Building Docker image (this may take a few minutes)...")

        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_ASSISTANT_DIR} && docker build -t rafi_assistant:latest .",
            timeout=600,  # 10 minutes for build
        )

        if exit_code != 0:
            raise DockerManagerError(
                f"Docker build failed (exit code {exit_code}):\n{err}"
            )

        logger.info("Docker image built successfully")
        print("Docker image built successfully.")

    finally:
        if own_connection:
            ssh_client.close()


def start_container(
    client_name: str,
    config_path: str | Path,
    env_vars: dict[str, str] | None = None,
) -> None:
    """Start a Docker container for a client.

    Creates the client directory on the EC2 instance, uploads the config
    file, generates an .env file, and starts the container using
    docker-compose.

    Args:
        client_name: Sanitized client name.
        config_path: Local path to the client config YAML file.
        env_vars: Optional dictionary of environment variables to set
            in the container's .env file.

    Raises:
        DockerManagerError: If any step fails.
    """
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise DockerManagerError(f"Config file not found: {config_path}")

    ssh_client = _connect_ssh()

    try:
        client_dir = f"{REMOTE_CLIENTS_DIR}/{client_name}"
        data_dir = f"{client_dir}/data"

        # Create client directories
        logger.info("Creating client directory: %s", client_dir)
        _exec_command(ssh_client, f"mkdir -p {client_dir} {data_dir}")

        # Upload config file
        remote_config = f"{client_dir}/config.yaml"
        _upload_file(ssh_client, config_path, remote_config)
        logger.info("Uploaded config to %s", remote_config)

        # Generate .env file
        env_content = _build_env_file(env_vars or {})
        remote_env = f"{client_dir}/.env"
        _upload_string(ssh_client, env_content, remote_env)
        logger.info("Created .env file at %s", remote_env)

        # Determine port
        port = _get_next_port(ssh_client)

        # Update docker-compose.yml
        _update_compose_file(ssh_client, client_name, port)

        # Ensure image is built
        out, _, _ = _exec_command(
            ssh_client,
            "docker images rafi_assistant:latest --format '{{.ID}}'",
        )
        if not out.strip():
            build_image(ssh_client)

        # Start the container
        logger.info("Starting container for client '%s' on port %d", client_name, port)
        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_BASE_DIR} && docker compose up -d client_{client_name}",
            timeout=120,
        )

        if exit_code != 0:
            raise DockerManagerError(
                f"Failed to start container for '{client_name}':\n{err}"
            )

        logger.info("Container started for client '%s'", client_name)
        print(f"Container started for '{client_name}' on port {port}")

    finally:
        ssh_client.close()


def _build_env_file(env_vars: dict[str, str]) -> str:
    """Build the content of a .env file from a dictionary.

    Args:
        env_vars: Dictionary of environment variable name-value pairs.

    Returns:
        String content for the .env file.
    """
    lines = []
    for key, value in sorted(env_vars.items()):
        # Escape any quotes in values
        safe_value = value.replace('"', '\\"')
        lines.append(f'{key}="{safe_value}"')
    return "\n".join(lines) + "\n"


def _update_compose_file(
    ssh_client: paramiko.SSHClient,
    client_name: str,
    port: int,
) -> None:
    """Add or update a client service in docker-compose.yml.

    Reads the existing compose file, adds the new client service
    definition, and writes it back.

    Args:
        ssh_client: Connected SSH client.
        client_name: Sanitized client name.
        port: Host port for the container.

    Raises:
        DockerManagerError: If the compose file cannot be updated.
    """
    import yaml

    # Read existing compose file or create a new one
    out, _, exit_code = _exec_command(
        ssh_client, f"cat {REMOTE_COMPOSE_FILE} 2>/dev/null || echo ''"
    )

    if out.strip():
        try:
            compose = yaml.safe_load(out)
        except yaml.YAMLError:
            compose = None
    else:
        compose = None

    if not isinstance(compose, dict):
        compose = {}

    # Ensure top-level structure
    if "services" not in compose:
        compose["services"] = {}

    service_name = f"client_{client_name}"
    client_dir = f"./clients/{client_name}"

    compose["services"][service_name] = {
        "build": "./rafi_assistant",
        "env_file": f"{client_dir}/.env",
        "volumes": [
            f"{client_dir}/config.yaml:/app/config.yaml:ro",
            f"{client_dir}/data:/data",
        ],
        "restart": "unless-stopped",
        "ports": [f"{port}:8000"],
    }

    # Serialize and upload
    compose_content = yaml.dump(compose, default_flow_style=False, sort_keys=False)
    _upload_string(ssh_client, compose_content, REMOTE_COMPOSE_FILE)
    logger.info("Updated docker-compose.yml with service '%s'", service_name)


def stop_container(client_name: str) -> None:
    """Stop a client's Docker container.

    Args:
        client_name: Sanitized client name.

    Raises:
        DockerManagerError: If the container cannot be stopped.
    """
    ssh_client = _connect_ssh()

    try:
        service_name = f"client_{client_name}"
        logger.info("Stopping container: %s", service_name)

        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_BASE_DIR} && docker compose stop {service_name}",
        )

        if exit_code != 0:
            raise DockerManagerError(
                f"Failed to stop container '{service_name}':\n{err}"
            )

        logger.info("Container stopped: %s", service_name)
        print(f"Container stopped: {client_name}")

    finally:
        ssh_client.close()


def restart_container(client_name: str) -> None:
    """Restart a client's Docker container.

    Args:
        client_name: Sanitized client name.

    Raises:
        DockerManagerError: If the container cannot be restarted.
    """
    ssh_client = _connect_ssh()

    try:
        service_name = f"client_{client_name}"
        logger.info("Restarting container: %s", service_name)

        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_BASE_DIR} && docker compose restart {service_name}",
        )

        if exit_code != 0:
            raise DockerManagerError(
                f"Failed to restart container '{service_name}':\n{err}"
            )

        logger.info("Container restarted: %s", service_name)
        print(f"Container restarted: {client_name}")

    finally:
        ssh_client.close()


def get_container_status(client_name: str) -> dict[str, str]:
    """Get the status of a client's Docker container.

    Args:
        client_name: Sanitized client name.

    Returns:
        Dictionary with 'status', 'health', 'uptime', and 'ports'.

    Raises:
        DockerManagerError: If the status cannot be retrieved.
    """
    ssh_client = _connect_ssh()

    try:
        service_name = f"client_{client_name}"

        # Get container info
        format_str = "{{.Status}}|{{.State}}|{{.Ports}}"
        out, err, exit_code = _exec_command(
            ssh_client,
            f"docker ps -a --filter 'name={service_name}' "
            f"--format '{format_str}'",
        )

        if exit_code != 0 or not out.strip():
            return {
                "status": "not_found",
                "health": "unknown",
                "uptime": "",
                "ports": "",
            }

        parts = out.strip().split("|")
        return {
            "status": parts[0] if len(parts) > 0 else "unknown",
            "health": parts[1] if len(parts) > 1 else "unknown",
            "uptime": parts[0] if len(parts) > 0 else "",
            "ports": parts[2] if len(parts) > 2 else "",
        }

    finally:
        ssh_client.close()


def get_container_logs(
    client_name: str, lines: int = 100
) -> str:
    """Get recent logs from a client's Docker container.

    Args:
        client_name: Sanitized client name.
        lines: Number of log lines to retrieve. Defaults to 100.

    Returns:
        Container log output as a string.

    Raises:
        DockerManagerError: If logs cannot be retrieved.
    """
    ssh_client = _connect_ssh()

    try:
        service_name = f"client_{client_name}"

        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_BASE_DIR} && docker compose logs --tail {lines} {service_name}",
        )

        if exit_code != 0:
            raise DockerManagerError(
                f"Failed to get logs for '{service_name}':\n{err}"
            )

        return out

    finally:
        ssh_client.close()


def remove_container(client_name: str, remove_data: bool = False) -> None:
    """Remove a client's Docker container and optionally its data.

    Args:
        client_name: Sanitized client name.
        remove_data: If True, also removes the client data directory.

    Raises:
        DockerManagerError: If removal fails.
    """
    ssh_client = _connect_ssh()

    try:
        service_name = f"client_{client_name}"

        # Stop and remove the container
        logger.info("Removing container: %s", service_name)
        out, err, exit_code = _exec_command(
            ssh_client,
            f"cd {REMOTE_BASE_DIR} && docker compose rm -sf {service_name}",
        )

        if exit_code != 0:
            logger.warning("Could not remove container '%s': %s", service_name, err)

        # Remove from docker-compose.yml
        _remove_from_compose(ssh_client, client_name)

        # Optionally remove client data
        if remove_data:
            client_dir = f"{REMOTE_CLIENTS_DIR}/{client_name}"
            _exec_command(ssh_client, f"rm -rf {client_dir}")
            logger.info("Removed client data directory: %s", client_dir)

        logger.info("Container removed: %s", service_name)
        print(f"Container removed: {client_name}")

    finally:
        ssh_client.close()


def _remove_from_compose(
    ssh_client: paramiko.SSHClient, client_name: str
) -> None:
    """Remove a client service from docker-compose.yml.

    Args:
        ssh_client: Connected SSH client.
        client_name: Sanitized client name.
    """
    import yaml

    out, _, exit_code = _exec_command(
        ssh_client, f"cat {REMOTE_COMPOSE_FILE} 2>/dev/null || echo ''"
    )

    if not out.strip():
        return

    try:
        compose = yaml.safe_load(out)
    except yaml.YAMLError:
        logger.warning("Could not parse docker-compose.yml for cleanup")
        return

    if not isinstance(compose, dict) or "services" not in compose:
        return

    service_name = f"client_{client_name}"
    if service_name in compose["services"]:
        del compose["services"][service_name]
        compose_content = yaml.dump(
            compose, default_flow_style=False, sort_keys=False
        )
        _upload_string(ssh_client, compose_content, REMOTE_COMPOSE_FILE)
        logger.info("Removed '%s' from docker-compose.yml", service_name)
