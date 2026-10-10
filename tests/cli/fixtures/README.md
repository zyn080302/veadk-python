`studio_updater_history.zip` contains 20 unmodified source modules from four
historical Studio consumer contracts. Each source path, commit and SHA256 is
recorded in the archive's `sources.json`, verified before importing any fixture.

The covered contracts are CLI 0.52.14 full-only, 0.52.14 thin-capable, 0.52.18
and 0.52.19. No original Studio implementation has yet been established for
0.52.15–0.52.17; these versions are **unverified**, not inferred from a neighbor.

Run `python -m tests.cli.fixtures.prepare_studio_history <input-directory>` to
download the exact public native archives before offline testing. Then set
`STUDIO_HISTORY_CLI_DIR` to that directory and run the historical consumer tests.
The release workflow requires these inputs and tests; missing inputs fail the
gate. No archive downloads or cloud calls occur during the tests themselves.

The tests use genuine native archives, original readers/extractors and startup
script generation, with a small metadata wheel. They establish the checksum
RED/GREEN contract, not dependency installation, CLI execution or cloud release.
Those require complete release artifacts and separate end-to-end acceptance.
