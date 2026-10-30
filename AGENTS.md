# Rules for coding agents in this repository

- Language of code, comments, docs and commit messages: **English**. Python 3.10 or newer; compatible with 3.10 to 3.14.
- **Standard library only** in `sealed/` and `tests/` (tests run with `pytest`, which is the only dev dependency). No network access while working, no installing packages.
- **Never** write real personal data, real case files, keys, tokens or `.env` files. All sample data in `examples/` is invented.
- The API key is read only from the environment variable `NEARAI_API_KEY`. Never print it, never write it to a file, never put it in a test.
- Before any text leaves the machine it must pass the pseudonymiser and its leak check. Do not add a code path that sends unchecked text.
- Do not change `docs/SPEC.md`, `docs/NEARAI_API.md`, `tests/vectors/*`, `fixtures/*`, `LICENSE`, `AGENTS.md`. If the spec looks wrong, say so in the final report instead of working around it.
- No `eval`/`exec`, no `shell=True`, no `pickle`. Type hints on public functions. Keep modules small and plain.
- Tests: plain `def test_*` functions with `assert`; use only `pytest` features `tmp_path`, `monkeypatch`, `capsys`, `pytest.raises`, `pytest.mark.parametrize`.
