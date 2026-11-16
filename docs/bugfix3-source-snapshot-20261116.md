# BugFix3 veADK/Codex source — 2026-11-16

Base: `0b8abf78110e6b93da4fb6e00099217e475d6bbe`. This source branch applies the seven exact Python module changes from the
SDK selected by BugFix3's frozen business candidate, including failed-turn settlement, PDF
message handling and unlimited finalization. All other 744 packaged `veadk/` files match the base.
The Codex implementation remains under `veadk/runtime/codex/` and `veadk/cli/codex_app_server.py`.

Selected SDK version:
`1.1.18.dev22+g0b8abf78.cfa97bfab82e1.failedturnv23.aff88a47f3ed.unlimitedfinalv11.936f162e3f6b`.
The original selected artifact and build definitions remain in the business snapshot; building
this branch with setuptools-scm may derive a different version and does not reproduce release approval.

Business source, integration tests and gate registration:
https://code.byted.org/iaas/tianyancha_online_stack/tree/codex/bugfix3-source-20261116

SDK-specific integration tests include `tests/customer_native_runtime/test_sdk_unlimited_finalization_v11.py`,
`tests/sdk_successor_admission/test_unlimited_admission_v16.py` and backend failed-turn/SDK tests in
that repository. Existing unit tests and specifications remain in this SDK repository.

The seven changed modules parse successfully and their bytes match the selected wheel.
The full integrated regression has not passed; no deployment or live acceptance is claimed.
