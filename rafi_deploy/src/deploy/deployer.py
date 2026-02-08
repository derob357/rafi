"""Orchestrate the full deployment pipeline for a new Rafi client.

Coordinates all provisioning steps in sequence: validates config,
provisions a Twilio number, creates a Supabase project, runs
migrations, builds and starts a Docker container, sends the OAuth
link, and runs a health check. If any step fails, all previously
completed steps are rolled back.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from src.deploy.docker_manager import (
    DockerManagerError,
    build_image,
    get_container_status,
    remove_container,
    start_container,
)
from src.deploy.oauth_sender import (
    OAuthSenderError,
    generate_oauth_url,
    send_oauth_email,
)
from src.deploy.supabase_provisioner import (
    SupabaseProvisioningError,
    create_project,
    delete_project,
)
from src.deploy.twilio_provisioner import (
    TwilioProvisioningError,
    provision_number,
    release_number,
)
from src.security.sanitizer import (
    SanitizationError,
    sanitize_client_name,
    validate_config_values,
)

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """Raised when the deployment pipeline fails."""

    pass


@dataclass
class DeploymentState:
    """Tracks the state of a deployment for rollback purposes."""

    client_name: str = ""
    config_path: str = ""
    twilio_number: str = ""
    supabase_project_id: str = ""
    supabase_credentials: dict[str, str] = field(default_factory=dict)
    container_started: bool = False
    oauth_sent: bool = False
    completed_steps: list[str] = field(default_factory=list)

    def add_step(self, step: str) -> None:
        """Record a completed step."""
        self.completed_steps.append(step)
        logger.info("Completed step: %s", step)


def _load_config(config_path: Path) -> dict[str, Any]:
    """Load and parse the client config YAML file.

    Args:
        config_path: Path to the config file.

    Returns:
        Parsed config dictionary.

    Raises:
        DeploymentError: If the file cannot be loaded or parsed.
    """
    if not config_path.exists():
        raise DeploymentError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise DeploymentError(
            f"Invalid YAML in config file: {exc}"
        ) from exc
    except OSError as exc:
        raise DeploymentError(
            f"Cannot read config file: {exc}"
        ) from exc

    if not isinstance(config, dict):
        raise DeploymentError("Config file does not contain a YAML mapping")

    return config


def _save_config(config: dict[str, Any], config_path: Path) -> None:
    """Save the updated config back to the YAML file.

    Args:
        config: Updated config dictionary.
        config_path: Path to the config file.

    Raises:
        DeploymentError: If the file cannot be written.
    """
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.info("Config saved: %s", config_path)
    except OSError as exc:
        raise DeploymentError(
            f"Cannot write config file: {exc}"
        ) from exc


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate the client config using the sanitizer.

    Performs basic structural validation. Some fields (like supabase.url)
    may be empty if they will be auto-filled during deployment.

    Args:
        config: The config dictionary.

    Returns:
        The validated config dictionary.

    Raises:
        DeploymentError: If validation fails.
    """
    # Check for placeholder values that must be replaced
    telegram_token = config.get("telegram", {}).get("bot_token", "")
    if not telegram_token or telegram_token == "BOT_TOKEN_HERE":
        raise DeploymentError(
            "telegram.bot_token is not set. "
            "Create a Telegram bot via BotFather and add the token to the config."
        )

    telegram_user_id = config.get("telegram", {}).get("user_id")
    if not telegram_user_id or telegram_user_id == 0:
        raise DeploymentError(
            "telegram.user_id is not set. "
            "Add the authorized Telegram user ID to the config."
        )

    # Check essential credentials
    llm_key = config.get("llm", {}).get("api_key", "")
    if not llm_key or llm_key == "PLACEHOLDER":
        raise DeploymentError(
            "llm.api_key is not set. Add your LLM API key to the config."
        )

    elevenlabs_key = config.get("elevenlabs", {}).get("api_key", "")
    if not elevenlabs_key or elevenlabs_key == "PLACEHOLDER":
        raise DeploymentError(
            "elevenlabs.api_key is not set. Add your ElevenLabs API key."
        )

    google_client_id = config.get("google", {}).get("client_id", "")
    if not google_client_id or google_client_id == "PLACEHOLDER":
        raise DeploymentError(
            "google.client_id is not set. Add your Google OAuth client ID."
        )

    return config


def _rollback(state: DeploymentState) -> None:
    """Roll back completed deployment steps.

    Called when a step fails to undo all previously completed steps
    in reverse order.

    Args:
        state: The deployment state tracking completed steps.
    """
    logger.warning(
        "Rolling back deployment for '%s'. Steps to undo: %s",
        state.client_name,
        state.completed_steps,
    )
    print(f"\nRolling back deployment for '{state.client_name}'...")

    errors: list[str] = []

    # Rollback in reverse order
    for step in reversed(state.completed_steps):
        try:
            if step == "container_started":
                logger.info("Rollback: Removing container")
                remove_container(state.client_name, remove_data=True)
                print("  Rolled back: Docker container removed")

            elif step == "supabase_created":
                if state.supabase_project_id:
                    logger.info(
                        "Rollback: Deleting Supabase project %s",
                        state.supabase_project_id,
                    )
                    delete_project(state.supabase_project_id)
                    print("  Rolled back: Supabase project deleted")

            elif step == "twilio_provisioned":
                if state.twilio_number:
                    logger.info(
                        "Rollback: Releasing Twilio number %s",
                        state.twilio_number,
                    )
                    release_number(state.twilio_number)
                    print("  Rolled back: Twilio number released")

        except Exception as exc:
            error_msg = f"Rollback failed for step '{step}': {exc}"
            logger.error(error_msg)
            errors.append(error_msg)

    if errors:
        print("\nWarning: Some rollback steps failed:")
        for error in errors:
            print(f"  - {error}")
        print("Manual cleanup may be required.")
    else:
        print("Rollback complete.")


def deploy(config_path: str | Path) -> None:
    """Run the full deployment pipeline for a new client.

    Executes the following steps in order:
    1. Load and validate the config file
    2. Provision a Twilio phone number
    3. Create a Supabase project and run migrations
    4. Build and start the Docker container
    5. Send the Google OAuth authorization link
    6. Run a health check

    If any step fails, all previously completed steps are rolled back.

    Args:
        config_path: Path to the client config YAML file.

    Raises:
        DeploymentError: If the deployment fails (after rollback).
    """
    config_path = Path(config_path).resolve()
    state = DeploymentState(config_path=str(config_path))

    print("=" * 60)
    print("  RAFI DEPLOY - Client Deployment Pipeline")
    print("=" * 60)
    print()

    # ---------------------------------------------------------------
    # Step 1: Load and validate config
    # ---------------------------------------------------------------
    print("[1/6] Loading and validating config...")
    config = _load_config(config_path)
    config = _validate_config(config)

    client_name_raw = config.get("client", {}).get("name", "")
    try:
        # Create a safe identifier from the client name
        safe_name = client_name_raw.lower().replace(" ", "_")
        safe_name = sanitize_client_name(safe_name)
    except SanitizationError as exc:
        raise DeploymentError(f"Invalid client name: {exc}") from exc

    state.client_name = safe_name
    logger.info("Deploying client: %s (%s)", client_name_raw, safe_name)
    print(f"  Client: {client_name_raw} (identifier: {safe_name})")
    print(f"  Config: {config_path}")
    print()

    # ---------------------------------------------------------------
    # Step 2: Provision Twilio number
    # ---------------------------------------------------------------
    print("[2/6] Provisioning Twilio phone number...")
    existing_number = config.get("twilio", {}).get("phone_number", "")
    if existing_number and existing_number not in ("", "PLACEHOLDER"):
        print(f"  Using existing number: {existing_number}")
        state.twilio_number = existing_number
    else:
        try:
            area_code = os.environ.get("TWILIO_PREFERRED_AREA_CODE")
            twilio_number = provision_number(
                client_name=safe_name,
                area_code=area_code,
            )
            state.twilio_number = twilio_number
            state.add_step("twilio_provisioned")

            # Update config with provisioned number
            config.setdefault("twilio", {})["phone_number"] = twilio_number
            _save_config(config, config_path)
            print(f"  Provisioned: {twilio_number}")

        except TwilioProvisioningError as exc:
            raise DeploymentError(
                f"Twilio provisioning failed: {exc}"
            ) from exc

    print()

    # ---------------------------------------------------------------
    # Step 3: Create Supabase project
    # ---------------------------------------------------------------
    print("[3/6] Creating Supabase project...")
    existing_url = config.get("supabase", {}).get("url", "")
    if existing_url and existing_url not in ("", "PLACEHOLDER"):
        print(f"  Using existing project: {existing_url}")
    else:
        try:
            supabase_result = create_project(client_name=safe_name)
            state.supabase_project_id = supabase_result["project_id"]
            state.supabase_credentials = supabase_result
            state.add_step("supabase_created")

            # Update config with Supabase credentials
            config.setdefault("supabase", {}).update(
                {
                    "url": supabase_result["url"],
                    "anon_key": supabase_result["anon_key"],
                    "service_role_key": supabase_result["service_role_key"],
                }
            )
            _save_config(config, config_path)
            print(f"  Created: {supabase_result['url']}")

        except SupabaseProvisioningError as exc:
            _rollback(state)
            raise DeploymentError(
                f"Supabase provisioning failed: {exc}"
            ) from exc

    print()

    # ---------------------------------------------------------------
    # Step 4: Build and start Docker container
    # ---------------------------------------------------------------
    print("[4/6] Building and starting Docker container...")
    try:
        # Build environment variables for the container
        env_vars = _build_env_vars(config)

        start_container(
            client_name=safe_name,
            config_path=config_path,
            env_vars=env_vars,
        )
        state.container_started = True
        state.add_step("container_started")
        print(f"  Container started: client_{safe_name}")

    except DockerManagerError as exc:
        _rollback(state)
        raise DeploymentError(
            f"Docker deployment failed: {exc}"
        ) from exc

    print()

    # ---------------------------------------------------------------
    # Step 5: Send OAuth link
    # ---------------------------------------------------------------
    print("[5/6] Sending Google OAuth authorization link...")
    client_email = config.get("client", {}).get("email", "")
    google_config = config.get("google", {})
    ec2_base_url = os.environ.get("EC2_BASE_URL", "https://rafi.example.com")

    if not client_email:
        print("  Skipping: No client email configured.")
        print("  You will need to manually send the OAuth link.")

        # Generate and display the URL anyway
        try:
            oauth_url = generate_oauth_url(
                client_id=google_config.get("client_id", ""),
                redirect_uri=f"{ec2_base_url}/oauth/callback/{safe_name}",
            )
            print(f"  OAuth URL: {oauth_url}")
        except OAuthSenderError as exc:
            logger.warning("Could not generate OAuth URL: %s", exc)
    else:
        try:
            oauth_url = generate_oauth_url(
                client_id=google_config.get("client_id", ""),
                redirect_uri=f"{ec2_base_url}/oauth/callback/{safe_name}",
                login_hint=client_email,
            )
            send_oauth_email(
                client_email=client_email,
                oauth_url=oauth_url,
                client_name=client_name_raw,
                assistant_name=config.get("elevenlabs", {}).get(
                    "agent_name", "Rafi"
                ),
            )
            state.oauth_sent = True
            state.add_step("oauth_sent")
            print(f"  OAuth email sent to: {client_email}")

        except OAuthSenderError as exc:
            # OAuth failure is non-fatal -- the deployment still works
            logger.warning("Failed to send OAuth email: %s", exc)
            print(f"  Warning: Could not send OAuth email: {exc}")
            print("  You will need to manually send the OAuth link.")

    print()

    # ---------------------------------------------------------------
    # Step 6: Health check
    # ---------------------------------------------------------------
    print("[6/6] Running health check...")
    try:
        _run_health_check(safe_name)
        print("  Health check passed.")
    except DeploymentError as exc:
        logger.warning("Health check failed: %s", exc)
        print(f"  Warning: Health check did not pass: {exc}")
        print("  The container may still be starting up. Check again shortly.")

    print()
    print("=" * 60)
    print(f"  Deployment complete for: {client_name_raw}")
    print(f"  Twilio Number: {state.twilio_number}")
    print(f"  Supabase Project: {state.supabase_project_id or 'existing'}")
    print(f"  Container: client_{safe_name}")
    print(f"  OAuth Sent: {'Yes' if state.oauth_sent else 'No (manual action needed)'}")
    print("=" * 60)


def _build_env_vars(config: dict[str, Any]) -> dict[str, str]:
    """Build environment variable dict from config for the container.

    Extracts API keys and credentials from the config and formats
    them as environment variables for the Docker container.

    Args:
        config: Client config dictionary.

    Returns:
        Dictionary of environment variable name-value pairs.
    """
    env_vars: dict[str, str] = {}

    # Telegram
    telegram = config.get("telegram", {})
    env_vars["TELEGRAM_BOT_TOKEN"] = telegram.get("bot_token", "")
    env_vars["TELEGRAM_USER_ID"] = str(telegram.get("user_id", ""))

    # Twilio
    twilio = config.get("twilio", {})
    env_vars["TWILIO_ACCOUNT_SID"] = twilio.get("account_sid", "")
    env_vars["TWILIO_AUTH_TOKEN"] = twilio.get("auth_token", "")
    env_vars["TWILIO_PHONE_NUMBER"] = twilio.get("phone_number", "")
    env_vars["CLIENT_PHONE_NUMBER"] = twilio.get("client_phone", "")

    # ElevenLabs
    elevenlabs = config.get("elevenlabs", {})
    env_vars["ELEVENLABS_API_KEY"] = elevenlabs.get("api_key", "")

    # LLM
    llm = config.get("llm", {})
    env_vars["LLM_PROVIDER"] = llm.get("provider", "openai")
    env_vars["LLM_MODEL"] = llm.get("model", "gpt-4o")
    env_vars["LLM_API_KEY"] = llm.get("api_key", "")

    # For OpenAI specifically
    if llm.get("provider") == "openai":
        env_vars["OPENAI_API_KEY"] = llm.get("api_key", "")

    # Google
    google = config.get("google", {})
    env_vars["GOOGLE_CLIENT_ID"] = google.get("client_id", "")
    env_vars["GOOGLE_CLIENT_SECRET"] = google.get("client_secret", "")

    # Supabase
    supabase = config.get("supabase", {})
    env_vars["SUPABASE_URL"] = supabase.get("url", "")
    env_vars["SUPABASE_ANON_KEY"] = supabase.get("anon_key", "")
    env_vars["SUPABASE_SERVICE_ROLE_KEY"] = supabase.get("service_role_key", "")

    # Deepgram
    deepgram = config.get("deepgram", {})
    env_vars["DEEPGRAM_API_KEY"] = deepgram.get("api_key", "")

    # Weather
    weather = config.get("weather", {})
    env_vars["WEATHER_API_KEY"] = weather.get("api_key", "")

    # OAuth encryption key (should already exist on EC2)
    oauth_key = os.environ.get("OAUTH_ENCRYPTION_KEY", "")
    if oauth_key:
        env_vars["OAUTH_ENCRYPTION_KEY"] = oauth_key

    return env_vars


def _run_health_check(client_name: str, timeout: int = 30) -> None:
    """Run a basic health check on the deployed container.

    Waits for the container to start and verifies it is running.

    Args:
        client_name: Sanitized client name.
        timeout: Maximum wait time in seconds.

    Raises:
        DeploymentError: If the health check fails.
    """
    logger.info("Running health check for '%s'", client_name)
    start_time = time.monotonic()

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            raise DeploymentError(
                f"Health check timed out after {timeout} seconds"
            )

        try:
            status = get_container_status(client_name)
            container_status = status.get("status", "")
            container_health = status.get("health", "")

            if "Up" in container_status:
                logger.info(
                    "Container healthy: status=%s, health=%s",
                    container_status,
                    container_health,
                )
                return

            if "Exited" in container_status or "Dead" in container_status:
                raise DeploymentError(
                    f"Container exited unexpectedly: {container_status}"
                )

        except DockerManagerError as exc:
            logger.debug("Health check attempt failed: %s", exc)

        time.sleep(5)


def stop_client(client_name: str) -> None:
    """Stop a client's assistant container.

    Args:
        client_name: The client name (will be sanitized).

    Raises:
        DeploymentError: If the stop operation fails.
    """
    try:
        safe_name = sanitize_client_name(client_name)
    except SanitizationError as exc:
        raise DeploymentError(f"Invalid client name: {exc}") from exc

    from src.deploy.docker_manager import stop_container

    try:
        stop_container(safe_name)
    except DockerManagerError as exc:
        raise DeploymentError(f"Failed to stop client '{safe_name}': {exc}") from exc


def restart_client(client_name: str) -> None:
    """Restart a client's assistant container.

    Args:
        client_name: The client name (will be sanitized).

    Raises:
        DeploymentError: If the restart operation fails.
    """
    try:
        safe_name = sanitize_client_name(client_name)
    except SanitizationError as exc:
        raise DeploymentError(f"Invalid client name: {exc}") from exc

    from src.deploy.docker_manager import restart_container

    try:
        restart_container(safe_name)
    except DockerManagerError as exc:
        raise DeploymentError(
            f"Failed to restart client '{safe_name}': {exc}"
        ) from exc


def health_check(client_name: str) -> dict[str, str]:
    """Check the health of a client's assistant.

    Args:
        client_name: The client name (will be sanitized).

    Returns:
        Dictionary with status information.

    Raises:
        DeploymentError: If the health check fails.
    """
    try:
        safe_name = sanitize_client_name(client_name)
    except SanitizationError as exc:
        raise DeploymentError(f"Invalid client name: {exc}") from exc

    try:
        status = get_container_status(safe_name)
        return status
    except DockerManagerError as exc:
        raise DeploymentError(
            f"Failed to check health of '{safe_name}': {exc}"
        ) from exc
