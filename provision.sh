#!/usr/bin/env bash
# =============================================================================
# provision.sh — Idempotent Azure AI Foundry provisioning for Synthie
# =============================================================================
# Usage:
#   export REGION=eastus
#   export RESOURCE_GROUP=rg-synthie
#   ./provision.sh
#
# Supported Voice Live regions:
#   eastus, eastus2, westus2, westeurope, swedencentral,
#   southeastasia, centralindia, japaneast, australiaeast
#
# Prerequisites:
#   • Azure CLI >= 2.60  (az --version)
#   • az login completed (az account show to verify)
#   • Contributor or Owner on the target subscription / resource group
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# 1.  CONFIGURATION
# ---------------------------------------------------------------------------
: "${REGION:?ERROR: Set REGION env var. e.g. export REGION=eastus}"
: "${RESOURCE_GROUP:?ERROR: Set RESOURCE_GROUP env var. e.g. export RESOURCE_GROUP=rg-synthie}"

ACCOUNT_NAME="${ACCOUNT_NAME:-foundry-${RESOURCE_GROUP}}"
PROJECT_NAME="${PROJECT_NAME:-synthie-project}"
MODEL_DEPLOYMENT_NAME="${MODEL_DEPLOYMENT_NAME:-gpt-4-1}"
MODEL_NAME="${MODEL_NAME:-gpt-4.1}"
MODEL_VERSION="${MODEL_VERSION:-}"
MODEL_CAPACITY="${MODEL_CAPACITY:-10}"

echo ""
echo "======================================================="
echo "  Synthie — Azure AI Foundry provisioning"
echo "======================================================="
echo "  Resource group  : $RESOURCE_GROUP"
echo "  Region          : $REGION"
echo "  Account name    : $ACCOUNT_NAME"
echo "  Project name    : $PROJECT_NAME"
echo "  Model deployment: $MODEL_DEPLOYMENT_NAME ($MODEL_NAME)"
echo "======================================================="
echo ""

# ---------------------------------------------------------------------------
# 2.  VERIFY AZ LOGIN
# ---------------------------------------------------------------------------
echo ">>> Verifying az login..."
az account show --query "{subscription:name, id:id}" -o table
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo ""

# ---------------------------------------------------------------------------
# 3.  RESOURCE GROUP  (idempotent)
# ---------------------------------------------------------------------------
echo ">>> Creating resource group '$RESOURCE_GROUP' in '$REGION'..."
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$REGION" \
    --output none
echo "    ✓ Resource group ready."
echo ""

# ---------------------------------------------------------------------------
# 4.  AI SERVICES ACCOUNT  (idempotent)
# ---------------------------------------------------------------------------
echo ">>> Creating AIServices account '$ACCOUNT_NAME'..."
az cognitiveservices account create \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --kind "AIServices" \
    --sku "S0" \
    --location "$REGION" \
    --custom-domain "$ACCOUNT_NAME" \
    --allow-project-management true \
    --yes \
    --output none 2>/dev/null || true
# Add custom domain to existing account if not set (idempotent)
az cognitiveservices account update \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --custom-domain "$ACCOUNT_NAME" \
    --output none 2>/dev/null || true
echo "    ✓ AIServices account ready."
echo ""

# ---------------------------------------------------------------------------
# 5.  PROJECT  (idempotent)
# ---------------------------------------------------------------------------
echo ">>> Creating project '$PROJECT_NAME'..."
az cognitiveservices account project create \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --project-name "$PROJECT_NAME" \
    --location "$REGION" \
    --output none 2>/dev/null || echo "    (Project already exists — skipping.)"
echo "    ✓ Project ready."
echo ""

# ---------------------------------------------------------------------------
# 6.  MODEL DEPLOYMENT  (idempotent)
# ---------------------------------------------------------------------------
echo ">>> Creating model deployment '$MODEL_DEPLOYMENT_NAME'..."

# model-version is required by the CLI; default to latest known if not set
_model_version="${MODEL_VERSION:-2025-04-14}"

az cognitiveservices account deployment create \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --deployment-name "$MODEL_DEPLOYMENT_NAME" \
    --model-name "$MODEL_NAME" \
    --model-version "$_model_version" \
    --model-format "OpenAI" \
    --sku-name "GlobalStandard" \
    --sku-capacity "$MODEL_CAPACITY" \
    --output none 2>/dev/null || echo "    (Deployment already exists — skipping.)"
echo "    ✓ Model deployment ready."
echo ""

# ---------------------------------------------------------------------------
# 7.  RBAC — assign current user Foundry User + Cognitive Services User
# ---------------------------------------------------------------------------
echo ">>> Assigning RBAC roles to current user..."
CURRENT_UPN=$(az account show --query user.name -o tsv)

RESOURCE_ID=$(az cognitiveservices account show \
    --name "$ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id -o tsv)

CURRENT_OID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
for ROLE in "Azure AI Developer" "Cognitive Services User"; do
    if [[ -n "$CURRENT_OID" ]]; then
        az role assignment create \
            --assignee-object-id "$CURRENT_OID" \
            --assignee-principal-type User \
            --role "$ROLE" \
            --scope "$RESOURCE_ID" \
            --output none 2>/dev/null || echo "    ($ROLE already assigned — skipping.)"
    fi
done
echo "    ✓ RBAC roles ready."
echo ""

# ---------------------------------------------------------------------------
# 8.  PRINT .env VALUES
# ---------------------------------------------------------------------------
VOICELIVE_ENDPOINT="https://${ACCOUNT_NAME}.cognitiveservices.azure.com/"
PROJECT_ENDPOINT="https://${ACCOUNT_NAME}.cognitiveservices.azure.com/api/projects/${PROJECT_NAME}"

echo "======================================================="
echo "  Provisioning complete! Copy these values to .env:"
echo "======================================================="
echo ""
echo "PROJECT_ENDPOINT=${PROJECT_ENDPOINT}"
echo "PROJECT_NAME=${PROJECT_NAME}"
echo "VOICELIVE_ENDPOINT=${VOICELIVE_ENDPOINT}"
echo "MODEL_DEPLOYMENT_NAME=${MODEL_DEPLOYMENT_NAME}"
echo "AGENT_NAME=synthie"
echo "VOICELIVE_API_VERSION=2026-04-10"
echo "AZURE_VOICE=en-US-AvaNeural"
echo "REGION=${REGION}"
echo "RESOURCE_GROUP=${RESOURCE_GROUP}"
echo "PERSONA_FILE=personas/default.md"
echo ""
echo "======================================================="
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env  (then paste the values above)"
echo "  2. python create_agent.py"
echo "  3. python main.py"
echo ""
