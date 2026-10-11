"""Résumé structuré via l'API Claude (sortie JSON validée par Pydantic)."""
from __future__ import annotations

import logging
from typing import Protocol

from pydantic import BaseModel, Field

from noter.analyzer.prompts import TEMPLATES, user_prompt
from noter.models import ActionItem, Summary

logger = logging.getLogger(__name__)


class ActionOut(BaseModel):
    text: str = Field(description="L'action à faire, formulée clairement")
    owner: str | None = Field(default=None, description="Prénom/nom du responsable si mentionné")
    due: str | None = Field(default=None, description="Échéance si mentionnée, telle quelle")


class SummaryOut(BaseModel):
    tldr: str = Field(description="Résumé en quelques phrases")
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    actions: list[ActionOut] = Field(default_factory=list)


class Summarizer(Protocol):
    name: str

    def summarize(self, transcript: str, duration_text: str, title: str | None, template: str) -> SummaryOut: ...


class ClaudeSummarizer:
    def __init__(self, api_key: str, model: str = "claude-opus-5-5", effort: str = "medium"):
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY manquante. Ajoute-la dans ~/Noter/.env (ANTHROPIC_API_KEY=sk-ant-...)."
            )
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.effort = effort
        self.name = model

    def summarize(self, transcript: str, duration_text: str, title: str | None, template: str = "default") -> SummaryOut:
        system = TEMPLATES.get(template, TEMPLATES["default"])
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": user_prompt(transcript, duration_text, title)}],
            output_format=SummaryOut,
        )
        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            raise RuntimeError(f"Claude a refusé la requête ({getattr(detail, 'category', '?')})")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Réponse Claude tronquée (max_tokens) — transcript trop long")
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError("Réponse Claude sans JSON exploitable")
        usage = response.usage
        logger.info("Claude %s : %d tokens in / %d out", self.model, usage.input_tokens, usage.output_tokens)
        return parsed


class FakeSummarizer:
    """Pour les tests : renvoie un résumé déterministe sans appel réseau."""

    name = "fake"

    def __init__(self, result: SummaryOut | None = None, fail_times: int = 0):
        self.result = result or SummaryOut(
            tldr="Résumé de test.",
            key_points=["Point A", "Point B"],
            decisions=["On part sur l'option 1"],
            actions=[ActionOut(text="Envoyer le devis", owner="Nassim", due="vendredi")],
        )
        self.fail_times = fail_times
        self.calls = 0

    def summarize(self, transcript: str, duration_text: str, title: str | None, template: str = "default") -> SummaryOut:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("échec simulé")
        return self.result


def to_summary(recording_id: str, model: str, template: str, out: SummaryOut) -> Summary:
    return Summary(
        recording_id=recording_id,
        model=model,
        template=template,
        tldr=out.tldr.strip(),
        key_points=[p.strip() for p in out.key_points if p.strip()],
        decisions=[d.strip() for d in out.decisions if d.strip()],
        actions=[ActionItem(text=a.text.strip(), owner=a.owner, due=a.due) for a in out.actions if a.text.strip()],
        raw_json=out.model_dump_json(),
    )
