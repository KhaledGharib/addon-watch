# Contributing

Bug reports and patches are welcome.

```console
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The rules that decide what a change costs live in `src/addon_watch/watcher.py`
and are covered by tests; `cli.py` holds the process handling. A change to
the rules should come with a test that states it in those terms.
