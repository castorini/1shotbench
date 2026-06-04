from __future__ import annotations

from dataclasses import dataclass, field

from bench.schemas import WorkspaceConfig


DEFAULT_TOOLS = ["read", "bash", "edit", "write", "grep", "find", "ls"]
DEFAULT_REQUIRED_SKILLS = [
    "install-anserini-fatjar",
    "anserini-cli",
    "anserini-reproduction",
]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    provider: str
    model: str
    thinking: str = "high"
    tools: list[str] = field(default_factory=lambda: DEFAULT_TOOLS.copy())
    required_skills: list[str] = field(default_factory=lambda: DEFAULT_REQUIRED_SKILLS.copy())

    def to_workspace_config(self) -> WorkspaceConfig:
        return WorkspaceConfig(
            key=self.key,
            name=self.name,
            path="",
            model=self.model,
            provider=self.provider,
            thinking=self.thinking,
            tools=list(self.tools),
            required_skills=list(self.required_skills),
        )

    def to_toml(self) -> str:
        return "\n".join(
            [
                f'name = "{self.name}"',
                f'provider = "{self.provider}"',
                f'model = "{self.model}"',
                f'thinking = "{self.thinking}"',
                f"tools = {_toml_list(self.tools)}",
                f"required_skills = {_toml_list(self.required_skills)}",
                "",
            ]
        )


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


MODEL_SPECS = [
    ModelSpec("gpt", "GPT workspace", "openai-codex", "gpt-5.5"),
    ModelSpec("claude", "Claude workspace", "anthropic", "claude-sonnet-4-6"),
    ModelSpec("gemini", "Gemini workspace", "google", "gemini-3.1-pro-preview"),
    ModelSpec("glm", "GLM workspace", "zai", "glm-5.1"),
    ModelSpec("kimi", "Kimi workspace", "moonshotai", "kimi-k2.6"),
    ModelSpec("minimax", "MiniMax workspace", "minimax", "MiniMax-M2.7"),
    ModelSpec("deepseek-flash", "DeepSeek workspace", "deepseek", "deepseek-v4-flash"),
    ModelSpec("deepseek-pro", "DeepSeek workspace", "deepseek", "deepseek-v4-pro"),
]


def load_model_catalog() -> dict[str, WorkspaceConfig]:
    return {spec.key: spec.to_workspace_config() for spec in MODEL_SPECS}


def find_model_spec(key: str) -> ModelSpec | None:
    for spec in MODEL_SPECS:
        if spec.key == key:
            return spec
    return None
