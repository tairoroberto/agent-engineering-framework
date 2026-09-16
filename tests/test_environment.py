from __future__ import annotations

import sys
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


if __name__ == "__main__":
    unittest.main()
