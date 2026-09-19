# addon-watch

[![test](https://github.com/KhaledGharib/addon-watch/actions/workflows/test.yml/badge.svg)](https://github.com/KhaledGharib/addon-watch/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/addon-watch.svg)](https://pypi.org/project/addon-watch/)
[![Python](https://img.shields.io/pypi/pyversions/addon-watch.svg)](https://pypi.org/project/addon-watch/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A live-reload runner for Odoo addons.** Runs the server, and when an addon
changes restarts it, upgrading only the modules that actually changed.

Odoo's own `--dev=all` reload needs the `watchdog` package and, even with it,
only re-imports Python. A new field, a changed view, a new access rule or a
migration still needs `-u`, which means stopping the server, remembering
which module you touched, and typing it out. `addon-watch` does that part.

```console
$ addon-watch -c odoo.conf -d demo
watching /srv/addons for .py .xml .csv .sql .yml .yaml
>> /usr/bin/python3 /opt/odoo/odoo-bin -c odoo.conf -d demo --dev=all

** sale_order.py, sale_order_views.xml changed -> -u sales_extra
>> /usr/bin/python3 /opt/odoo/odoo-bin -c odoo.conf -d demo --dev=all -u sales_extra

** portal.py changed (code only, no upgrade)
>> /usr/bin/python3 /opt/odoo/odoo-bin -c odoo.conf -d demo --dev=all
```

No dependencies, one file of logic, Python 3.8+.

## Install

```console
pip install addon-watch
```

Or run it straight from a checkout, with no install at all:

```console
python3 -m addon_watch -c odoo.conf -d demo
```

## Use

```console
addon-watch -c odoo.conf -d demo
```

`odoo-bin` is found in the current directory or above it, then on `PATH`;
`--odoo-bin` names it directly. What gets watched comes from the config's
`addons_path`, minus anything inside the Odoo install itself — core addons
are not what you are editing, and a stray touch there would upgrade half the
database. `--addons DIR` (repeatable) overrides that.

Anything after `--` goes to `odoo-bin`:

```console
addon-watch -c odoo.conf -d demo -- --http-port=8070 --log-level=warn
```

| Option | What it does |
| --- | --- |
| `-d`, `--database` | Database to run against. |
| `-c`, `--config` | Odoo config file; its `addons_path` decides what is watched. |
| `--addons DIR` | Watch this directory. Repeatable; replaces the config's list. |
| `--modules A,B` | Upgrade these on every restart instead of what changed. |
| `--upgrade-on-start` | Upgrade on the first boot too. Off by default. |
| `--odoo-bin PATH` | The `odoo-bin` to run. |
| `--python PATH` | The interpreter that runs it. Defaults to the current one. |
| `--ext .EXT` | Watch this extension. Repeatable. |
| `--code-only-dir NAME` | A directory inside a module that never needs `-u`. Repeatable. |
| `--poll SECONDS` | How often to scan. Default `0.2`. |

## What it decides

**Which files matter.** `.py`, `.xml`, `.csv`, `.sql`, `.yml`, `.yaml` — the
things a running Odoo cannot pick up on its own. `static/` is skipped on
purpose: `--dev=all` serves those from disk, so a change there needs a
browser reload, not a restart. (Browsers cache `static/src/js` files hard,
because the URL carries the module version; hard-reload after editing one.)

**Which module changed.** A module is the nearest directory above the file
that holds a `__manifest__.py`, and the search stops at the watched root.
Editing `crm_extra` does not pay for upgrading `sales_extra`.

**Whether the database needs telling.** Changes under a module's
`controllers/`, `tests/`, `tools/` or `lib/` restart without `-u`: nothing
there is stored in the database, and skipping the upgrade is about a second
faster. Everything else — models, views, security, data, migrations,
manifests — gets `-u`.

When Odoo dies on a traceback, the watcher stops and waits for your next
edit instead of restart-looping over the same failure.

## Why polling

A scan of a few hundred addon files takes about a millisecond, so the poll
loop costs nothing and an event-based watcher (`watchdog`, `watchexec`,
`fswatch`) would save nothing measurable — while adding a dependency and a
platform surface. The latency that matters is the poll interval and the
debounce, both 0.2s, and Odoo's own boot, which is seconds.

## Development

```console
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## License

MIT