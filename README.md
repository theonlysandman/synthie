# Synthie — Synthetic Customer Voice Agent

Synthie is a synthetic customer persona that runs on **Azure AI Foundry** + **Voice Live**. It simulates realistic customers (billing queries, support calls, upgrade enquiries) so you can test and evaluate your own voice AI agents without involving real people.

---

## Architecture

```
Your mic  ──►  Voice Live WebSocket  ──►  Synthie (Foundry Agent)  ──►  Your speaker
                                              │
                                     Instructions + persona
                                     (instructions.md + personas/)
```

Synthie speaks *as a customer*. You (or your agent-under-test) speak as the contact centre agent.

---

## Prerequisites

| Tool | Min version | Check |
|------|-------------|-------|
| Python | 3.10 | `python --version` |
| Azure CLI | 2.60 | `az --version` |
| PortAudio (for PyAudio) | any | see [Audio setup](#audio-setup) |
| `az login` completed | — | `az account show` |

Supported **Voice Live regions**: `eastus`, `eastus2`, `westus2`, `westeurope`, `swedencentral`, `southeastasia`, `centralindia`, `japaneast`, `australiaeast`.

---

## Quickstart

```bash
# 1. Clone and install
git clone https://github.com/<your-org>/synthie.git
cd synthie
pip install -r requirements.txt

# 2. Provision Azure resources (bash/WSL/Git Bash)
export REGION=eastus
export RESOURCE_GROUP=rg-synthie
bash provision.sh

# 3. Configure
cp .env.example .env
# Paste the PROJECT_ENDPOINT / VOICELIVE_ENDPOINT values printed by provision.sh

# 4. Create the Foundry agent
python create_agent.py

# 5. Start the voice loop
python main.py
```

---

## Customising Synthie

### Change the persona

Edit `personas/default.md` or create a new file under `personas/` and update `PERSONA_FILE` in `.env`.

The persona file is appended to `instructions.md` at agent creation time, so every `create_agent.py` run picks up the latest version.

### Change the scenario

Edit `instructions.md` — specifically the **Scenarios** section. The Foundry agent is updated every time you run `create_agent.py` (a new agent version is created).

### Change the voice

Update `AZURE_VOICE` in `.env`. Browse available voices at https://aka.ms/tts-voices.

---

## CI/CD — auto-push on changes

Every push to `main` that touches `instructions.md`, `personas/**`, or `create_agent.py` triggers the GitHub Actions workflow at [.github/workflows/deploy-agent.yml](.github/workflows/deploy-agent.yml). It logs in to Azure via OIDC and runs `create_agent.py` automatically.

### One-time setup

See the setup comments at the top of `.github/workflows/deploy-agent.yml`. In brief:

1. Create a service principal: `az ad sp create-for-rbac --name synthie-gh-actions`
2. Add a federated credential (repo: `<org>/synthie`, subject: `repo:<org>/synthie:ref:refs/heads/main`)
3. Assign `Azure AI Foundry User` + `Cognitive Services User` roles to the SP
4. Add three GitHub Actions **secrets**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
5. Add three GitHub Actions **variables**: `PROJECT_ENDPOINT`, `MODEL_DEPLOYMENT_NAME`, `AGENT_NAME`

---

## Audio setup

### Windows
PyAudio installs via pip on most Python versions. If it fails:
```powershell
pip install pipwin; pipwin install pyaudio
```

### macOS
```bash
brew install portaudio
pip install pyaudio
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get install portaudio19-dev python3-pyaudio
pip install pyaudio
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `DefaultAzureCredential / AzureCliCredential failed` | Run `az login` |
| `HTTP 403` on agent create | Check RBAC: you need `Azure AI Foundry User` + `Cognitive Services User` on the AI Services resource |
| `HTTP 404` on connect | Verify `VOICELIVE_ENDPOINT` ends in `.services.ai.azure.com/` (no `/api/projects/...`) |
| No audio input | Check mic permissions; try `python -c "import pyaudio; p=pyaudio.PyAudio(); print(p.get_default_input_device_info())"` |
| `TypeError: connect() got unexpected keyword argument 'agent_config'` | Update SDK: `pip install --upgrade azure-ai-voicelive[aiohttp]` |

---

## Repo structure

```
synthie/
├── .github/
│   └── workflows/
│       └── deploy-agent.yml   ← CI/CD: auto-push agent on changes
├── personas/
│   └── default.md             ← Customer persona (appended to instructions)
├── .env.example               ← Config template
├── .gitignore
├── create_agent.py            ← Idempotent Foundry agent creation
├── instructions.md            ← Synthie system prompt
├── main.py                    ← Real-time voice loop
├── provision.sh               ← Azure resource provisioning
├── README.md
└── requirements.txt
```
