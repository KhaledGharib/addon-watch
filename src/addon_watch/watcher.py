"""Watch Odoo addons and decide what a change costs.

The rules live here, away from the process handling, because they are the
part worth reading and testing: which files matter, which module a path
belongs to, and whether a change has to reach the database at all.
"""

from __future__ import annotations

import os

# The files a running Odoo cannot pick up on its own. Everything a module
# stores in the database arrives through one of these.
DEFAULT_EXTENSIONS = ('.py', '.xml', '.csv', '.sql', '.yml', '.yaml')

# Never worth walking, and static/ is served from disk under --dev=all: a
# change there needs a browser reload, not a restart.
DEFAULT_SKIP_DIRS = frozenset({
    '__pycache__', '.git', '.hg', '.svn', '.idea', '.vscode',
    'node_modules', 'static', '.mypy_cache', '.pytest_cache', '.ruff_cache',
})

# Directories inside a module that hold no field, view, access rule or
# migration: changing one only means the code has to be re-imported, so the
# restart can skip -u and the upgrade it costs.
DEFAULT_CODE_ONLY_DIRS = ('controllers', 'tests', 'tools', 'lib')


def snapshot(roots, extensions=DEFAULT_EXTENSIONS, skip_dirs=DEFAULT_SKIP_DIRS):
    """Every watched file's mtime under ``roots``, keyed by path."""
    seen = {}
    for root in roots:
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if not name.endswith(tuple(extensions)):
                    continue
                path = os.path.join(base, name)
                try:
                    seen[path] = os.stat(path).st_mtime
                except OSError:
                    # Deleted between the walk and the stat. The next pass
                    # reports it as a change, which is what it is.
                    pass
    return seen


def changed(before, after):
    """The paths that appeared, vanished or were written, sorted."""
    paths = set(before) ^ set(after)
    paths |= {p for p in set(before) & set(after) if before[p] != after[p]}
    return sorted(paths)


def module_of(path, roots):
    """The module a file belongs to, as ``(name, subpath)``.

    A module is the nearest directory above the file that holds a manifest,
    and the search stops at the watched root so a stray manifest further up
    the tree cannot claim the file. ``(None, None)`` when the file is not in
    a module.
    """
    path = os.path.abspath(path)
    boundaries = {os.path.abspath(r) for r in roots}
    current = os.path.dirname(path)
    while True:
        for manifest in ('__manifest__.py', '__openerp__.py'):
            if os.path.isfile(os.path.join(current, manifest)):
                return os.path.basename(current), os.path.relpath(path, current)
        if current in boundaries:
            return None, None
        parent = os.path.dirname(current)
        if parent == current:
            return None, None
        current = parent


def modules_to_upgrade(paths, roots, code_only_dirs=DEFAULT_CODE_ONLY_DIRS):
    """The modules these changes have to reach the database through.

    Empty when every change is code the server only has to re-import, so the
    restart can skip -u. Order follows the paths, so the reason for an
    upgrade is readable in the log.
    """
    modules = []
    for path in paths:
        name, subpath = module_of(path, roots)
        if not name:
            continue
        head = subpath.split(os.sep)[0] if os.sep in subpath else ''
        if head and head in code_only_dirs:
            continue
        if name not in modules:
            modules.append(name)
    return modules


def read_addons_path(config_path, cwd=None):
    """The ``addons_path`` of an Odoo config file, as absolute paths.

    A relative entry is resolved the way Odoo resolves it, against the
    working directory, and against the config's own directory only as a
    fallback for the layouts where that is what was meant.

    Read by hand rather than with configparser: an Odoo config is close
    enough to INI that the one line worth having is easy to find, and a file
    with a duplicate key or an odd section must not stop the watcher.
    """
    paths = []
    try:
        with open(config_path, encoding='utf-8') as handle:
            lines = handle.readlines()
    except OSError:
        return paths
    bases = [cwd or os.path.abspath(os.curdir),
             os.path.dirname(os.path.abspath(config_path))]
    for line in lines:
        key, sep, value = line.partition('=')
        if not sep or key.strip() != 'addons_path':
            continue
        for entry in value.split(','):
            entry = entry.strip()
            if not entry:
                continue
            if os.path.isabs(entry):
                paths.append(os.path.normpath(entry))
                continue
            candidates = [os.path.normpath(os.path.join(b, entry))
                          for b in bases]
            existing = [c for c in candidates if os.path.isdir(c)]
            paths.append(existing[0] if existing else candidates[0])
    return paths


def is_under(path, parent):
    """Whether ``path`` is ``parent`` or sits inside it."""
    path = os.path.abspath(path)
    parent = os.path.abspath(parent)
    return path == parent or path.startswith(parent + os.sep)
