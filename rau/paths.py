"""Project paths for the Rau runtime."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAU_PKG = Path(__file__).resolve().parent
IDENTITY_DIR = ROOT / "identity"
IDENTITY_EXAMPLES = IDENTITY_DIR / "examples"
MEMORIES_DIR = ROOT / "memories"
DIARY_DIR = MEMORIES_DIR / "diary"
TRACES_DIR = MEMORIES_DIR / "traces"
DAILY_DIR = MEMORIES_DIR / "daily"
GOALS_DIR = MEMORIES_DIR / "goals"
ACTIVE_GOAL = GOALS_DIR / "active.json"
CONFIG_DIR = ROOT / "config"
SKILLS_DIR = ROOT / "skills"
WEB_DIST = ROOT / "web" / "dist"
ASSETS_DIR = ROOT / "assets"
SFX_DIR = ASSETS_DIR / "sfx"
SECRETS_DIR = ROOT / "secrets"
ENV_FILE = ROOT / ".env"

IDENTITY_MD = IDENTITY_DIR / "identity.md"
BACKSTORY_MD = IDENTITY_DIR / "backstory.md"
SOUL_MD = IDENTITY_DIR / "soul.md"
SOUL_BAK = IDENTITY_DIR / "soul.bak.md"
MODELS_CONFIG = CONFIG_DIR / "models.json"
MCP_CONFIG = CONFIG_DIR / "mcp.json"
SETTINGS_CONFIG = CONFIG_DIR / "settings.json"


def ensure_dirs() -> None:
    for d in (
        IDENTITY_DIR,
        IDENTITY_EXAMPLES,
        MEMORIES_DIR,
        DIARY_DIR,
        TRACES_DIR,
        DAILY_DIR,
        GOALS_DIR,
        CONFIG_DIR,
        SKILLS_DIR,
        ASSETS_DIR,
        SFX_DIR,
        SECRETS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
