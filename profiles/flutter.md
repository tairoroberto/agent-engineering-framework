# Flutter profile

Discover Flutter/Dart toolchain, package layout, workspace tooling, `analysis_options.yaml`, CI, and project test conventions before changes. Prefer project wrappers when present. Typical candidates to verify from the repository, never assume: `dart format`, `flutter analyze`, `flutter test`, code generation, and build commands. Cover behavior with existing Flutter/Dart test patterns. Product localization, DI, analytics, release, and architecture stay project-owned.

For Developer Closure, select checks by the affected behavior. After related
edits, format only changed Dart files once when needed. Analyze the affected
package only for analysis-relevant changes; run focused tests that exercise the
changed behavior. Copy/docs/assets-only work does not automatically require Dart
formatting, analysis or widget tests. Use full regression, goldens, code
generation or build only for affected contracts, explicit acceptance/project
requirements or risk. Reuse current evidence and rerun only checks invalidated
by a fix. `core/verification.md` owns the shared selection rules.

The shared OpenCode QA adapter may execute only the non-mutating formatting check
`dart format --output=none --set-exit-if-changed`, `flutter analyze`, `flutter test`,
and Git diff/status diagnostics. It remains unable to edit source, specifications,
state, handoffs, or validation reports. Project-specific gates stay project-owned.
