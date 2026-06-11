"""
create_agent.py — Idempotent Foundry Agent creation for Synthie
===============================================================
Creates (or updates) the Synthie Foundry Agent backed by
MODEL_DEPLOYMENT_NAME, with system instructions from instructions.md
and optionally an appended persona from PERSONA_FILE.

Authentication: AzureCliCredential (local) or WorkloadIdentityCredential
(GitHub Actions via OIDC — set AZURE_CLIENT_ID / AZURE_TENANT_ID /
AZURE_SUBSCRIPTION_ID in your workflow environment).

Usage:
    python create_agent.py

Required env vars (set in .env):
    PROJECT_ENDPOINT      - https://<resource>.services.ai.azure.com/api/projects/<project>
    MODEL_DEPLOYMENT_NAME - name of the deployed chat model
    AGENT_NAME            - desired agent name (will be created if missing)

Optional env vars:
    PERSONA_FILE          - path (relative to repo root) to append to instructions
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import AzureCliCredential, WorkloadIdentityCredential
from azure.core.exceptions import HttpResponseError

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------
load_dotenv()

_REQUIRED = ["PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME", "AGENT_NAME"]
_missing = [v for v in _REQUIRED if not os.environ.get(v)]
if _missing:
    sys.exit(
        f"ERROR: The following required environment variables are not set:\n"
        + "\n".join(f"  - {v}" for v in _missing)
        + "\n\nCopy .env.example to .env and fill in the values, "
        "then re-run this script."
    )

PROJECT_ENDPOINT: str = os.environ["PROJECT_ENDPOINT"]
MODEL_DEPLOYMENT_NAME: str = os.environ["MODEL_DEPLOYMENT_NAME"]
AGENT_NAME: str = os.environ["AGENT_NAME"]
PERSONA_FILE: str = os.environ.get("PERSONA_FILE", "")

# ---------------------------------------------------------------------------
# Build system instructions
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).parent
_instructions_path = _repo_root / "instructions.md"
if not _instructions_path.exists():
    sys.exit(
        f"ERROR: {_instructions_path} not found.\n"
        "Create instructions.md with the agent's system prompt, then re-run."
    )
INSTRUCTIONS: str = _instructions_path.read_text(encoding="utf-8").strip()

# Optionally append persona
if PERSONA_FILE:
    _persona_path = _repo_root / PERSONA_FILE
    if _persona_path.exists():
        persona_text = _persona_path.read_text(encoding="utf-8").strip()
        INSTRUCTIONS = f"{INSTRUCTIONS}\n\n---\n## Active persona\n\n{persona_text}"
        print(f"Persona loaded from: {_persona_path}")
    else:
        print(f"Warning: PERSONA_FILE '{PERSONA_FILE}' not found — using base instructions only.")

# ---------------------------------------------------------------------------
# Credential — supports both local (az login) and CI (OIDC)
# ---------------------------------------------------------------------------
_client_id = os.environ.get("AZURE_CLIENT_ID", "")
_tenant_id = os.environ.get("AZURE_TENANT_ID", "")
_token_file = os.environ.get("AZURE_FEDERATED_TOKEN_FILE", "")

if _client_id and _tenant_id and _token_file:
    # GitHub Actions OIDC path — azure/login@v2 sets AZURE_FEDERATED_TOKEN_FILE
    credential = WorkloadIdentityCredential(
        client_id=_client_id,
        tenant_id=_tenant_id,
        token_file_path=_token_file,
    )
    print("Using WorkloadIdentityCredential (GitHub Actions OIDC)")
else:
    # Local developer path
    credential = AzureCliCredential()
    print("Using AzureCliCredential (local az login)")

# ---------------------------------------------------------------------------
# Connect and create/update agent
# ---------------------------------------------------------------------------
print(f"Connecting to project: {PROJECT_ENDPOINT}")

with AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as client:

    # Idempotency: check whether an agent with this name already exists.
    existing = None
    try:
        for item in client.agents.list():
            if getattr(item, "name", None) == AGENT_NAME:
                existing = item
                break
    except HttpResponseError as exc:
        print(f"Note: agents.list() returned HTTP {exc.status_code}; will attempt creation.")
    except Exception as exc:  # noqa: BLE001
        print(f"Note: agents.list() raised {type(exc).__name__}: {exc}; will attempt creation.")

    if existing is not None:
        print(
            f"\n✓ Agent '{AGENT_NAME}' already exists — creating new version with updated instructions.\n"
            f"  ID     : {existing.id}"
        )
        # Force a new version to pick up instruction changes
        agent = client.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=MODEL_DEPLOYMENT_NAME,
                instructions=INSTRUCTIONS,
            ),
        )
        print(
            f"\n✓ Agent version created.\n"
            f"  Name   : {agent.name}\n"
            f"  ID     : {agent.id}\n"
            f"  Version: {agent.version}"
        )
    else:
        print(f"\nCreating agent '{AGENT_NAME}' with model '{MODEL_DEPLOYMENT_NAME}'...")
        try:
            agent = client.agents.create_version(
                agent_name=AGENT_NAME,
                definition=PromptAgentDefinition(
                    model=MODEL_DEPLOYMENT_NAME,
                    instructions=INSTRUCTIONS,
                ),
            )
        except HttpResponseError as exc:
            sys.exit(
                f"ERROR: Failed to create agent.\n"
                f"  HTTP {exc.status_code} — {exc.reason}\n"
                f"  {exc.message}\n\n"
                "Check that MODEL_DEPLOYMENT_NAME is correct and the deployment "
                "is in a 'Succeeded' state:\n"
                "  az cognitiveservices account deployment show "
                "-n <account> -g <rg> --deployment-name <name>"
            )

        print(
            f"\n✓ Agent created successfully.\n"
            f"  Name   : {agent.name}\n"
            f"  ID     : {agent.id}\n"
            f"  Version: {agent.version}\n"
            f"\nAdd to .env:\n"
            f"  AGENT_NAME={agent.name}"
        )
        if hasattr(agent, "version"):
            print(f"  AGENT_VERSION={agent.version}")
