"""CLI entry point for rafi-deploy.

Provides subcommands for the full onboarding and deployment workflow:
  - onboard: Record an onboarding interview and transcribe it
  - extract: Generate a client config from a transcript
  - deploy:  Deploy a client's assistant instance
  - stop:    Stop a client's assistant
  - restart: Restart a client's assistant
  - health:  Check the health of a client's assistant

Usage:
    rafi-deploy onboard --audio /path/to/recording.wav
    rafi-deploy extract --transcript /path/to/transcript.txt --output /path/to/config.yaml
    rafi-deploy deploy --config /path/to/client_config.yaml
    rafi-deploy stop --client john_doe
    rafi-deploy restart --client john_doe
    rafi-deploy health --client john_doe
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from pythonjsonlogger.json import JsonFormatter


def _configure_logging(verbose: bool = False) -> None:
    """Configure structured JSON logging.

    Args:
        verbose: If True, set log level to DEBUG; otherwise INFO.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)

    formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def _cmd_onboard(args: argparse.Namespace) -> int:
    """Handle the 'onboard' subcommand.

    Records audio from the microphone (if no audio path given)
    or transcribes an existing audio file.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.onboarding.recorder import RecordingError, record_interview
    from src.onboarding.transcriber import TranscriptionError, transcribe_audio

    audio_path = Path(args.audio) if args.audio else None

    # Step 1: Record if no audio provided
    if audio_path is None:
        default_output = Path.cwd() / "onboarding_interview.wav"
        try:
            audio_path = record_interview(output_path=default_output)
        except RecordingError as exc:
            print(f"Error: Recording failed: {exc}", file=sys.stderr)
            return 1
    else:
        if not audio_path.exists():
            print(f"Error: Audio file not found: {audio_path}", file=sys.stderr)
            return 1
        print(f"Using existing audio file: {audio_path}")

    # Step 2: Transcribe
    try:
        transcript = transcribe_audio(audio_path)
        print(f"\nTranscription complete ({len(transcript)} characters).")
        print("Run 'rafi-deploy extract' to generate the config file.")
        return 0
    except TranscriptionError as exc:
        print(f"Error: Transcription failed: {exc}", file=sys.stderr)
        return 1


def _cmd_extract(args: argparse.Namespace) -> int:
    """Handle the 'extract' subcommand.

    Extracts client config from a transcript file using LLM.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.onboarding.config_extractor import (
        ConfigExtractionError,
        extract_config,
    )

    transcript_path = Path(args.transcript)
    output_path = Path(args.output) if args.output else transcript_path.with_suffix(".yaml")

    if not transcript_path.exists():
        print(f"Error: Transcript file not found: {transcript_path}", file=sys.stderr)
        return 1

    try:
        result_path = extract_config(
            transcript_path=transcript_path,
            output_path=output_path,
            interactive=not args.non_interactive,
        )
        print(f"\nConfig extracted to: {result_path}")
        return 0
    except ConfigExtractionError as exc:
        print(f"Error: Config extraction failed: {exc}", file=sys.stderr)
        return 1


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Handle the 'deploy' subcommand.

    Runs the full deployment pipeline for a client.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.deploy.deployer import DeploymentError, deploy

    config_path = Path(args.config)

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        deploy(config_path=config_path)
        return 0
    except DeploymentError as exc:
        print(f"\nError: Deployment failed: {exc}", file=sys.stderr)
        return 1


def _cmd_stop(args: argparse.Namespace) -> int:
    """Handle the 'stop' subcommand.

    Stops a client's assistant container.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.deploy.deployer import DeploymentError, stop_client

    try:
        stop_client(args.client)
        print(f"Client '{args.client}' stopped.")
        return 0
    except DeploymentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_restart(args: argparse.Namespace) -> int:
    """Handle the 'restart' subcommand.

    Restarts a client's assistant container.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.deploy.deployer import DeploymentError, restart_client

    try:
        restart_client(args.client)
        print(f"Client '{args.client}' restarted.")
        return 0
    except DeploymentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_health(args: argparse.Namespace) -> int:
    """Handle the 'health' subcommand.

    Checks the health of a client's assistant.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    from src.deploy.deployer import DeploymentError, health_check

    try:
        status = health_check(args.client)
        print(f"\nHealth status for '{args.client}':")
        for key, value in status.items():
            print(f"  {key}: {value}")

        container_status = status.get("status", "")
        if "Up" in container_status:
            print("\nStatus: HEALTHY")
            return 0
        elif status.get("status") == "not_found":
            print("\nStatus: NOT FOUND")
            return 1
        else:
            print(f"\nStatus: UNHEALTHY ({container_status})")
            return 1

    except DeploymentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser with all subcommands.

    Returns:
        Configured argparse.ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="rafi-deploy",
        description="Onboarding and deployment tools for Rafi AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  rafi-deploy onboard --audio recording.wav
  rafi-deploy extract --transcript transcript.txt --output config.yaml
  rafi-deploy deploy --config client_config.yaml
  rafi-deploy stop --client john_doe
  rafi-deploy restart --client john_doe
  rafi-deploy health --client john_doe
""",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        description="Available subcommands",
    )

    # --- onboard ---
    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Record and transcribe an onboarding interview",
        description=(
            "Records audio from the microphone (or uses an existing file) "
            "and transcribes it using Deepgram."
        ),
    )
    onboard_parser.add_argument(
        "--audio",
        type=str,
        default=None,
        help="Path to an existing audio file to transcribe (skips recording)",
    )

    # --- extract ---
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract client config from a transcript",
        description=(
            "Uses an LLM to extract client configuration details from "
            "an onboarding interview transcript."
        ),
    )
    extract_parser.add_argument(
        "--transcript",
        type=str,
        required=True,
        help="Path to the transcript text file",
    )
    extract_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for the config YAML (default: same as transcript with .yaml extension)",
    )
    extract_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip interactive prompts for missing fields",
    )

    # --- deploy ---
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy a client's assistant instance",
        description=(
            "Runs the full deployment pipeline: provisions Twilio number, "
            "creates Supabase project, builds and starts Docker container, "
            "sends OAuth link."
        ),
    )
    deploy_parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to the client config YAML file",
    )

    # --- stop ---
    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop a client's assistant",
        description="Stops the Docker container for a client's assistant.",
    )
    stop_parser.add_argument(
        "--client",
        type=str,
        required=True,
        help="Client name (identifier, e.g., john_doe)",
    )

    # --- restart ---
    restart_parser = subparsers.add_parser(
        "restart",
        help="Restart a client's assistant",
        description="Restarts the Docker container for a client's assistant.",
    )
    restart_parser.add_argument(
        "--client",
        type=str,
        required=True,
        help="Client name (identifier, e.g., john_doe)",
    )

    # --- health ---
    health_parser = subparsers.add_parser(
        "health",
        help="Check health of a client's assistant",
        description="Checks the Docker container status for a client's assistant.",
    )
    health_parser.add_argument(
        "--client",
        type=str,
        required=True,
        help="Client name (identifier, e.g., john_doe)",
    )

    return parser


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def main() -> None:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    _configure_logging(verbose=args.verbose)

    # Dispatch to the appropriate command handler
    command_handlers = {
        "onboard": _cmd_onboard,
        "extract": _cmd_extract,
        "deploy": _cmd_deploy,
        "stop": _cmd_stop,
        "restart": _cmd_restart,
        "health": _cmd_health,
    }

    handler = command_handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        exit_code = handler(args)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        exit_code = 130
    except Exception as exc:
        logging.getLogger(__name__).exception("Unexpected error")
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
