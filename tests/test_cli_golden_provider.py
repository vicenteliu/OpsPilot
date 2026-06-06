"""Tests for the ``opspilot harness golden-provider`` CLI command.

The command swaps the base playbook's chat model for an arbitrary provider
so ``make harness-matrix`` can exercise all 6 providers on one fixture. We
mock ``_harness_dispatch`` to assert the Model override is built and passed
through correctly, without a live provider or KB.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from opspilot.cli import _infer_model_kind, app

runner = CliRunner()


class TestKindInference:
    def test_anthropic(self) -> None:
        assert _infer_model_kind("anthropic") == "anthropic"

    def test_ollama(self) -> None:
        assert _infer_model_kind("ollama-local") == "ollama"

    def test_openai_compatible_default(self) -> None:
        # openai / openrouter / gemini / grok all route through the openai kind.
        assert _infer_model_kind("grok") == "openai"
        assert _infer_model_kind("openai") == "openai"


class TestGoldenProviderPassesModelOverride:
    def test_grok_override_built_and_dispatched(self) -> None:
        with patch("opspilot.cli._harness_dispatch", return_value=0) as mock_dispatch:
            result = runner.invoke(
                app,
                [
                    "harness",
                    "golden-provider",
                    "--provider",
                    "grok",
                    "--model",
                    "grok-3-mini",
                ],
            )

        assert result.exit_code == 0
        mock_dispatch.assert_called_once()
        override = mock_dispatch.call_args.kwargs["model_override"]
        assert override.provider_id == "grok"
        assert override.kind == "openai"  # inferred
        assert override.name == "grok-3-mini"

    def test_explicit_kind_overrides_inference(self) -> None:
        with patch("opspilot.cli._harness_dispatch", return_value=0) as mock_dispatch:
            result = runner.invoke(
                app,
                [
                    "harness",
                    "golden-provider",
                    "--provider",
                    "ollama-local",
                    "--model",
                    "gemma4:e4b",
                    "--kind",
                    "ollama",
                ],
            )

        assert result.exit_code == 0
        override = mock_dispatch.call_args.kwargs["model_override"]
        assert override.kind == "ollama"

    def test_nonzero_dispatch_propagates_exit_code(self) -> None:
        with patch("opspilot.cli._harness_dispatch", return_value=2):
            result = runner.invoke(
                app,
                ["harness", "golden-provider", "--provider", "openai", "--model", "gpt-4o-mini"],
            )

        assert result.exit_code == 2
