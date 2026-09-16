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


class InstallRunner(FakeRunner):
    def run(self, argv: tuple[str, ...], *, timeout: float = 10) -> environment.CommandResult:
        normalized = tuple(argv)
        if "tar" in Path(normalized[0]).name and "-C" in normalized:
            extracted = Path(normalized[normalized.index("-C") + 1]) / "release"
            template = extracted / "packaging" / "launchd" / environment.AI_MEMORY_LAUNCH_AGENT
            template.parent.mkdir(parents=True)
            (extracted / "ai-memory").write_text("binary\n", encoding="utf-8")
            template.write_text("__AI_MEMORY_BIN__\n__HOME__\n", encoding="utf-8")
        return super().run(normalized, timeout=timeout)


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

    def test_authorized_macos_install_selects_architecture_initializes_and_bootstraps_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            root = Path(raw) / "project"
            home.mkdir()
            root.mkdir()
            label = f"gui/{environment.os.getuid()}/{environment.AI_MEMORY_LABEL}"
            runner = InstallRunner({
                ("/bin/curl", "--fail", "--location", "--silent", "--show-error", "--output"): environment.CommandResult(("placeholder",), 0),
                ("/bin/launchctl", "print", label): environment.CommandResult(("/bin/launchctl", "print", label), 1),
            })
            original_run = runner.run

            def run(argv: tuple[str, ...], *, timeout: float = 10) -> environment.CommandResult:
                normalized = tuple(argv)
                if normalized[0] == "/bin/curl":
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                if normalized[0] == "/bin/tar":
                    staging = Path(normalized[normalized.index("-C") + 1]) / "release"
                    template = staging / "packaging" / "launchd" / environment.AI_MEMORY_LAUNCH_AGENT
                    template.parent.mkdir(parents=True)
                    (staging / "ai-memory").write_text("binary\n", encoding="utf-8")
                    template.write_text("__AI_MEMORY_BIN__\n__HOME__\n", encoding="utf-8")
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                if normalized[0].endswith("/Applications/ai-memory/ai-memory") and normalized[1:] == ("init",):
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                if normalized[:2] == ("/bin/launchctl", "print"):
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 1)
                if normalized[:2] == ("/bin/launchctl", "bootstrap"):
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                return original_run(normalized, timeout=timeout)

            runner.run = run  # type: ignore[assignment]
            context = environment.EnvironmentContext(
                root=root,
                home=home,
                runner=runner,
                system="Darwin",
                architecture="arm64",
                executable_finder=lambda name: (
                    str(home / "Applications" / "ai-memory" / "ai-memory")
                    if name == "ai-memory" and (home / "Applications" / "ai-memory" / "ai-memory").is_file()
                    else {
                    "curl": "/bin/curl", "tar": "/bin/tar", "launchctl": "/bin/launchctl",
                    }.get(name)
                ),
            )

            operations = environment.AiMemoryRequirement(()).repair(
                context, environment.PlatformInfo("Darwin", "arm64"), {"ai-memory:install"},
            )

            self.assertTrue(all(operation.succeeded for operation in operations))
            self.assertTrue((home / "Applications" / "ai-memory" / "ai-memory").is_file())
            self.assertIn("aarch64.tar.gz", runner.calls[0][-1])
            plist = home / "Library" / "LaunchAgents" / environment.AI_MEMORY_LAUNCH_AGENT
            self.assertIn(str(home / "Applications" / "ai-memory" / "ai-memory"), plist.read_text(encoding="utf-8"))
            self.assertFalse(any(command[1:2] == ("bootout",) for command in runner.calls))

    def test_macos_install_rejects_an_unknown_architecture_without_running_commands(self) -> None:
        runner = FakeRunner({})
        operation = environment.AiMemoryRequirement(())._install_macos(
            self.context(runner), environment.PlatformInfo("Darwin", "ppc64"),
        )

        self.assertFalse(operation.succeeded)
        self.assertIn("unsupported architecture", operation.detail or "")
        self.assertFalse(runner.calls)

    def test_caveman_missing_offers_the_official_global_install_command(self) -> None:
        runner = FakeRunner({
            ("/bin/npx", "--no-install", "skills", "ls", "-g"): environment.CommandResult(("/bin/npx", "--no-install", "skills", "ls", "-g"), 0, stdout="other-skill\n"),
        })
        context = environment.EnvironmentContext(
            root=Path("/workspace"), home=Path("/home/tester"), runner=runner,
            system="Darwin", architecture="arm64", executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
        )
        result = environment.CavemanRequirement(()).diagnose(context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"))

        self.assertEqual(environment.RequirementStatus.MISSING, result.status)
        self.assertEqual(("caveman:install",), tuple(action.id for action in result.actions))

    def test_caveman_global_skill_without_a_known_codex_link_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            skill = home / ".config" / "opencode" / "skills" / "caveman"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: caveman\n---\n", encoding="utf-8")
            context = environment.EnvironmentContext(
                root=home, home=home, runner=FakeRunner({}), system="Darwin", architecture="arm64",
                executable_finder=lambda name: {"npx": "/bin/npx", "codex": "/bin/codex"}.get(name),
            )

            result = environment.CavemanRequirement(("codex",)).diagnose(context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"))

            self.assertEqual(environment.RequirementStatus.PARTIAL, result.status)
            self.assertEqual(environment.RequirementStatus.MISSING, next(check.status for check in result.checks if check.id == "codex-link"))

    def test_tlc_skill_with_unverified_origin_is_partial_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            skill = home / ".agents" / "skills" / "tlc-spec-driven"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: tlc-spec-driven\n---\n", encoding="utf-8")
            context = environment.EnvironmentContext(
                root=home, home=home, runner=FakeRunner({}), system="Darwin", architecture="arm64",
                executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
            )

            result = environment.TlcSpecDrivenRequirement(()).diagnose(context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"))

            self.assertEqual(environment.RequirementStatus.PARTIAL, result.status)
            self.assertEqual(("tlc-spec-driven:install",), tuple(action.id for action in result.actions))

    def test_tlc_install_rechecks_the_official_origin(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            runner = FakeRunner({})
            original_run = runner.run

            def run(argv: tuple[str, ...], *, timeout: float = 10) -> environment.CommandResult:
                normalized = tuple(argv)
                if normalized == (
                    "/bin/npx", "@tech-leads-club/agent-skills", "install",
                    "-s", "tlc-spec-driven", "-g",
                ):
                    skill = home / ".agents" / "skills" / "tlc-spec-driven"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text(
                        "---\nname: tlc-spec-driven\n---\n", encoding="utf-8",
                    )
                    (skill / ".skill-meta.json").write_text(
                        '{"source": "tech-leads-club/agent-skills"}\n', encoding="utf-8",
                    )
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                return original_run(normalized, timeout=timeout)

            runner.run = run  # type: ignore[assignment]
            context = environment.EnvironmentContext(
                root=home, home=home, runner=runner, system="Darwin", architecture="arm64",
                executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
            )

            operation = environment.TlcSpecDrivenRequirement(()).repair(
                context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"),
                {"tlc-spec-driven:install"},
            )[0]

            self.assertTrue(operation.succeeded)
            self.assertEqual("installed and verified", operation.detail)

    def test_tlc_install_failure_is_reported(self) -> None:
        command = (
            "/bin/npx", "@tech-leads-club/agent-skills", "install",
            "-s", "tlc-spec-driven", "-g",
        )
        runner = FakeRunner({command: environment.CommandResult(command, 1)})
        context = environment.EnvironmentContext(
            root=Path("/workspace"), home=Path("/home/tester"), runner=runner,
            system="Darwin", architecture="arm64",
            executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
        )

        operation = environment.TlcSpecDrivenRequirement(()).repair(
            context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"),
            {"tlc-spec-driven:install"},
        )[0]

        self.assertFalse(operation.succeeded)
        self.assertEqual("command exited 1", operation.detail)

    def test_skill_install_failure_is_retained_without_touching_other_requirements(self) -> None:
        runner = FakeRunner({
            ("/bin/npx", "skills", "add", "JuliusBrussee/caveman", "-g"): environment.CommandResult(("/bin/npx", "skills", "add", "JuliusBrussee/caveman", "-g"), 1),
        })
        context = environment.EnvironmentContext(
            root=Path("/workspace"), home=Path("/home/tester"), runner=runner,
            system="Darwin", architecture="arm64", executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
        )

        operation = environment.CavemanRequirement(()).repair(
            context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"), {"caveman:install"},
        )[0]

        self.assertFalse(operation.succeeded)
        self.assertEqual("command exited 1", operation.detail)

    def test_successful_caveman_install_is_rechecked_from_the_global_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            runner = FakeRunner({})
            original_run = runner.run

            def run(argv: tuple[str, ...], *, timeout: float = 10) -> environment.CommandResult:
                normalized = tuple(argv)
                if normalized == ("/bin/npx", "skills", "add", "JuliusBrussee/caveman", "-g"):
                    skill = home / ".agents" / "skills" / "caveman"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("---\nname: caveman\n---\n", encoding="utf-8")
                    runner.calls.append(normalized)
                    return environment.CommandResult(normalized, 0)
                return original_run(normalized, timeout=timeout)

            runner.run = run  # type: ignore[assignment]
            context = environment.EnvironmentContext(
                root=home, home=home, runner=runner, system="Darwin", architecture="arm64",
                executable_finder=lambda name: "/bin/npx" if name == "npx" else None,
            )

            operation = environment.CavemanRequirement(()).repair(
                context, environment.PlatformInfo("Darwin", "arm64", npx_version="11"), {"caveman:install"},
            )[0]

            self.assertTrue(operation.succeeded)
            self.assertEqual("installed and verified", operation.detail)


if __name__ == "__main__":
    unittest.main()
