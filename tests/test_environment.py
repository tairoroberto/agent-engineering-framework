from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


STATE_DIR = Path(__file__).resolve().parents[1] / "state"
if str(STATE_DIR) not in sys.path:
    sys.path.insert(0, str(STATE_DIR))

import environment


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], environment.CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, timeout: float = 10) -> environment.CommandResult:
        normalized = tuple(argv)
        self.calls.append(normalized)
        return self.results.get(normalized, environment.CommandResult(normalized, 127, error="not configured"))


class StaticRequirement(environment.EnvironmentRequirement):
    def __init__(self, result: environment.RequirementResult) -> None:
        self.id = result.id
        self.name = result.name
        self.description = result.description
        self.required = result.required
        self.result = result

    def diagnose(self, context: environment.EnvironmentContext, platform: environment.PlatformInfo) -> environment.RequirementResult:
        return self.result


class RaisingRequirement(environment.EnvironmentRequirement):
    id = "raising"
    name = "Raising"
    description = "Test-only failure"

    def diagnose(self, context: environment.EnvironmentContext, platform: environment.PlatformInfo) -> environment.RequirementResult:
        raise RuntimeError("do not leak")


class EnvironmentRuntimeTest(unittest.TestCase):
    def context(self, runner: FakeRunner | None = None) -> environment.EnvironmentContext:
        return environment.EnvironmentContext(
            root=Path("/workspace"),
            home=Path("/home/tester"),
            runner=runner or FakeRunner({}),
            system="Darwin",
            architecture="arm64",
            executable_finder=lambda _: None,
        )

    def result(
        self,
        requirement_id: str,
        status: environment.RequirementStatus,
        *,
        required: bool = True,
    ) -> environment.RequirementResult:
        return environment.RequirementResult(
            id=requirement_id,
            name=requirement_id,
            description="test requirement",
            required=required,
            status=status,
        )

    def test_requirement_status_distinguishes_missing_running_and_partial(self) -> None:
        self.assertEqual(
            environment.RequirementStatus.MISSING,
            environment.requirement_status((environment.CheckResult("binary", "binary", environment.RequirementStatus.MISSING),)),
        )
        self.assertEqual(
            environment.RequirementStatus.NOT_RUNNING,
            environment.requirement_status((environment.CheckResult("service", "service", environment.RequirementStatus.NOT_RUNNING),)),
        )
        self.assertEqual(
            environment.RequirementStatus.PARTIAL,
            environment.requirement_status((
                environment.CheckResult("binary", "binary", environment.RequirementStatus.OK),
                environment.CheckResult("service", "service", environment.RequirementStatus.NOT_RUNNING),
            )),
        )

    def test_optional_unsupported_check_does_not_make_a_requirement_unhealthy(self) -> None:
        self.assertEqual(
            environment.RequirementStatus.OK,
            environment.requirement_status((
                environment.CheckResult("mcp", "mcp", environment.RequirementStatus.OK),
                environment.CheckResult("hooks", "hooks", environment.RequirementStatus.UNSUPPORTED, required=False),
            )),
        )

    def test_report_is_healthy_only_when_every_required_requirement_is_ok(self) -> None:
        service = environment.EnvironmentService(
            self.context(),
            (
                StaticRequirement(self.result("healthy", environment.RequirementStatus.OK)),
                StaticRequirement(self.result("optional", environment.RequirementStatus.UNSUPPORTED, required=False)),
            ),
        )
        self.assertTrue(service.inspect().healthy)

        unresolved = environment.EnvironmentService(
            self.context(),
            (StaticRequirement(self.result("missing", environment.RequirementStatus.MISSING)),),
        ).inspect()
        self.assertFalse(unresolved.healthy)
        self.assertEqual("missing", unresolved.to_dict()["requirements"][0]["status"])

    def test_service_preserves_independent_results_after_a_requirement_failure(self) -> None:
        report = environment.EnvironmentService(
            self.context(),
            (
                RaisingRequirement(),
                StaticRequirement(self.result("healthy", environment.RequirementStatus.OK)),
            ),
        ).inspect()

        self.assertEqual(environment.RequirementStatus.ERROR, report.requirements[0].status)
        self.assertEqual("RuntimeError", report.requirements[0].checks[0].detail)
        self.assertEqual(environment.RequirementStatus.OK, report.requirements[1].status)

    def test_platform_collects_node_tools_independently(self) -> None:
        runner = FakeRunner({
            ("/bin/node", "--version"): environment.CommandResult(("/bin/node", "--version"), 0, stdout="v22.0.0\n"),
            ("/bin/npm", "--version"): environment.CommandResult(("/bin/npm", "--version"), 0, stdout="10.0.0\n"),
        })
        context = environment.EnvironmentContext(
            root=Path("/workspace"),
            home=Path("/home/tester"),
            runner=runner,
            system="Darwin",
            architecture="arm64",
            executable_finder=lambda name: {"node": "/bin/node", "npm": "/bin/npm"}.get(name),
        )

        facts = environment.inspect_platform(context)

        self.assertEqual("v22.0.0", facts.node_version)
        self.assertEqual("10.0.0", facts.npm_version)
        self.assertIsNone(facts.npx_version)
        self.assertEqual([("/bin/node", "--version"), ("/bin/npm", "--version")], runner.calls)

    def test_ai_memory_missing_on_macos_offers_only_the_official_install_action(self) -> None:
        result = environment.AiMemoryRequirement(("codex",)).diagnose(
            self.context(), environment.PlatformInfo("Darwin", "arm64"),
        )

        self.assertEqual(environment.RequirementStatus.MISSING, result.status)
        self.assertEqual(("ai-memory:install",), tuple(action.id for action in result.actions))
        self.assertEqual("aarch64", environment.architecture_artifact("arm64"))
        self.assertEqual("x86_64", environment.architecture_artifact("x86_64"))
        self.assertIsNone(environment.architecture_artifact("ppc64"))

    def test_ai_memory_running_with_http_405_and_integrations_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            root = Path(raw) / "project"
            data = home / "Library" / "Application Support" / "ai-memory"
            data.mkdir(parents=True)
            root.mkdir()
            (data / "config.toml").write_text("ready = true\n", encoding="utf-8")
            codex = home / ".codex"
            codex.mkdir()
            (codex / "config.toml").write_text("[mcp_servers.ai-memory]\n[hooks.ai-memory]\n", encoding="utf-8")
            opencode = home / ".config" / "opencode" / "plugins"
            opencode.mkdir(parents=True)
            (opencode.parent / "opencode.json").write_text('{"mcp":{"ai-memory":{}}}\n', encoding="utf-8")
            (opencode / "ai-memory.ts").write_text("ai-memory\n", encoding="utf-8")
            vscode = root / ".vscode"
            vscode.mkdir()
            (vscode / "mcp.json").write_text('{"servers":{"ai-memory":{}}}\n', encoding="utf-8")
            runner = FakeRunner({
                ("/bin/ai-memory", "--version"): environment.CommandResult(("/bin/ai-memory", "--version"), 0, stdout="ai-memory 2.1.0\n"),
                ("/bin/ai-memory", "status"): environment.CommandResult(("/bin/ai-memory", "status"), 0, stdout="connected\n"),
                ("/bin/launchctl", "print", f"gui/{environment.os.getuid()}/{environment.AI_MEMORY_LABEL}"): environment.CommandResult(("/bin/launchctl", "print", f"gui/{environment.os.getuid()}/{environment.AI_MEMORY_LABEL}"), 0, stdout="state = running\n"),
                ("/bin/curl", "--silent", "--show-error", "--output", environment.os.devnull, "--write-out", "%{http_code}", environment.AI_MEMORY_HTTP_URL): environment.CommandResult(("/bin/curl", "--silent", "--show-error", "--output", environment.os.devnull, "--write-out", "%{http_code}", environment.AI_MEMORY_HTTP_URL), 0, stdout="405"),
            })
            context = environment.EnvironmentContext(
                root=root,
                home=home,
                runner=runner,
                system="Darwin",
                architecture="arm64",
                executable_finder=lambda name: {
                    "ai-memory": "/bin/ai-memory", "launchctl": "/bin/launchctl", "curl": "/bin/curl",
                    "codex": "/bin/codex", "opencode": "/bin/opencode", "copilot": "/bin/copilot",
                }.get(name),
            )

            result = environment.AiMemoryRequirement(("codex", "opencode", "copilot")).diagnose(
                context, environment.inspect_platform(context),
            )

            self.assertEqual(environment.RequirementStatus.OK, result.status)
            self.assertEqual("HTTP 405", next(check.detail for check in result.checks if check.id == "http"))
            self.assertEqual(environment.RequirementStatus.UNSUPPORTED, next(check.status for check in result.checks if check.id == "copilot-hooks"))
            self.assertFalse(result.actions)

    def test_ai_memory_is_partial_when_launchd_is_loaded_but_http_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            data = home / "Library" / "Application Support" / "ai-memory"
            data.mkdir(parents=True)
            (data / "config.toml").write_text("ready = true\n", encoding="utf-8")
            runner = FakeRunner({
                ("/bin/ai-memory", "--version"): environment.CommandResult(("/bin/ai-memory", "--version"), 0, stdout="ai-memory 2.1.0\n"),
                ("/bin/ai-memory", "status"): environment.CommandResult(("/bin/ai-memory", "status"), 1, stderr="server unreachable\n"),
                ("/bin/launchctl", "print", f"gui/{environment.os.getuid()}/{environment.AI_MEMORY_LABEL}"): environment.CommandResult(("/bin/launchctl", "print", f"gui/{environment.os.getuid()}/{environment.AI_MEMORY_LABEL}"), 0, stdout="state = running\n"),
                ("/bin/curl", "--silent", "--show-error", "--output", environment.os.devnull, "--write-out", "%{http_code}", environment.AI_MEMORY_HTTP_URL): environment.CommandResult(("/bin/curl", "--silent", "--show-error", "--output", environment.os.devnull, "--write-out", "%{http_code}", environment.AI_MEMORY_HTTP_URL), 7, stdout="000"),
            })
            context = environment.EnvironmentContext(
                root=home,
                home=home,
                runner=runner,
                system="Darwin",
                architecture="arm64",
                executable_finder=lambda name: {"ai-memory": "/bin/ai-memory", "launchctl": "/bin/launchctl", "curl": "/bin/curl"}.get(name),
            )

            result = environment.AiMemoryRequirement(()).diagnose(context, environment.inspect_platform(context))

            self.assertEqual(environment.RequirementStatus.PARTIAL, result.status)
            self.assertEqual(environment.RequirementStatus.NOT_RUNNING, next(check.status for check in result.checks if check.id == "http"))
            self.assertEqual(("ai-memory:service",), tuple(action.id for action in result.actions))


if __name__ == "__main__":
    unittest.main()
