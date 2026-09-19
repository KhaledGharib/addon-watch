# Changelog

## 0.1.0

First release.

- Runs `odoo-bin` and restarts it when a watched file changes.
- Upgrades only the modules that changed, found by their manifest.
- Skips `-u` entirely for changes under `controllers/`, `tests/`, `tools/`
  and `lib/`, which the database knows nothing about.
- Reads what to watch from the config's `addons_path`, minus Odoo's own
  addons.
- Waits for an edit instead of restart-looping when Odoo dies on a traceback.
