# Flutter profile

Discover Flutter/Dart toolchain, package layout, workspace tooling, `analysis_options.yaml`, CI, and project test conventions before changes. Prefer project wrappers when present. Typical candidates to verify from the repository, never assume: `dart format`, `flutter analyze`, `flutter test`, code generation, and build commands. Cover behavior with existing Flutter/Dart test patterns. Product localization, DI, analytics, release, and architecture stay project-owned.

For Developer Closure, discover the smallest project-approved sequence for the
touched scope: format touched Dart files when applicable, analyze the relevant
package/project, then run focused component tests. Escalate to full regression,
goldens, code generation, or build only when task risk, project policy, or the
acceptance contract requires it. Record only command/result/scope facts.

The shared OpenCode QA adapter may execute only the non-mutating formatting check
`dart format --output=none --set-exit-if-changed`, `flutter analyze`, `flutter test`,
and Git diff/status diagnostics. It remains unable to edit source, specifications,
state, handoffs, or validation reports. Project-specific gates stay project-owned.
