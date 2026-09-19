"""Run Odoo and restart it when an addon changes."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time

from . import __version__
from .watcher import (
    DEFAULT_CODE_ONLY_DIRS,
    DEFAULT_EXTENSIONS,
    DEFAULT_SKIP_DIRS,
    changed,
    is_under,
    modules_to_upgrade,
    read_addons_path,
    snapshot,
)

# Both are latency the edit pays for, and a scan of a few hundred files costs
# about a millisecond, so there is nothing to gain by polling less often.
POLL = 0.2
DEBOUNCE = 0.2

CYAN, YELLOW, RED, RESET = '\033[36m', '\033[33m', '\033[31m', '\033[0m'


def say(color, message):
    if not sys.stdout.isatty():
        color = RESET
    print('%s%s%s' % (color, message, RESET), flush=True)


def find_odoo_bin(given):
    """The odoo-bin to run: the one given, one nearby, or one on PATH."""
    if given:
        return os.path.abspath(given)
    here = os.path.abspath(os.curdir)
    while True:
        candidate = os.path.join(here, 'odoo-bin')
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    for name in ('odoo-bin', 'odoo'):
        found = shutil.which(name)
        if found:
            return found
    return None


def can_run_odoo(python):
    """Whether this interpreter has Odoo's dependencies within reach.

    A virtualenv holding only addon-watch is the easy mistake: odoo-bin then
    dies on an import before it says anything useful about itself.
    """
    probe = 'import babel, werkzeug'
    try:
        return subprocess.run([python, '-c', probe], timeout=30,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def core_addons(odoo_bin):
    """Odoo's own addons directories, which nobody is editing.

    Only these two, not everything beside odoo-bin: a checkout that keeps
    custom addons inside the Odoo tree is a common layout, and dropping the
    whole tree would leave nothing to watch.
    """
    if not odoo_bin:
        return []
    root = os.path.dirname(os.path.abspath(odoo_bin))
    return [os.path.join(root, 'addons'), os.path.join(root, 'odoo', 'addons')]


def default_roots(config, odoo_bin, cwd=None):
    """What to watch when nothing was named: the config's ``addons_path``
    minus Odoo's own addons."""
    roots = []
    core = core_addons(odoo_bin)
    for path in read_addons_path(config, cwd) if config else []:
        if any(is_under(path, c) for c in core):
            continue
        if os.path.isdir(path) and path not in roots:
            roots.append(path)
    return roots or [os.path.abspath(cwd or os.curdir)]


class Server:
    """The odoo-bin process, and the only place that starts or stops one."""

    def __init__(self, command, cwd):
        self.command = command
        self.cwd = cwd
        self.process = None

    def start(self, modules):
        command = list(self.command)
        if modules:
            command += ['-u', ','.join(modules)]
        say(CYAN, '>> ' + ' '.join(command))
        # Its own process group, so a stop reaches the children Odoo forked
        # and nothing is left holding the HTTP port.
        self.process = subprocess.Popen(command, cwd=self.cwd,
                                        start_new_session=True)

    def stop(self, timeout=20):
        if not self.process or self.process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            self.process.wait()

    @property
    def returncode(self):
        return self.process.poll() if self.process else None


def build_parser():
    parser = argparse.ArgumentParser(
        prog='addon-watch',
        description="Run Odoo and restart it when an addon changes, "
                    "upgrading only the modules that changed.",
        epilog="Arguments after -- go to odoo-bin: "
               "addon-watch -d demo -- --http-port=8070")
    parser.add_argument('-d', '--database')
    parser.add_argument('-c', '--config',
                        help="Odoo config file. Its addons_path decides what "
                             "is watched when --addons is not given.")
    parser.add_argument('--addons', action='append', default=[], metavar='DIR',
                        help="A directory of addons to watch. Repeatable.")
    parser.add_argument('--modules', default='', metavar='A,B',
                        help="Upgrade these modules on every restart instead "
                             "of the ones that changed.")
    parser.add_argument('--upgrade-on-start', action='store_true',
                        help="Upgrade on the first boot too. Off by default: "
                             "the point of the first boot is to be up.")
    parser.add_argument('--odoo-bin', metavar='PATH',
                        help="Defaults to an odoo-bin in this directory or "
                             "above it, then to one on PATH.")
    parser.add_argument('--python', default=sys.executable,
                        help="The interpreter that runs odoo-bin.")
    parser.add_argument('--ext', action='append', default=[], metavar='.EXT',
                        help="A file extension to watch. Repeatable. "
                             "Default: %s." % ' '.join(DEFAULT_EXTENSIONS))
    parser.add_argument('--code-only-dir', action='append', default=[],
                        metavar='NAME',
                        help="A directory inside a module that never needs "
                             "-u. Repeatable. Default: %s."
                             % ' '.join(DEFAULT_CODE_ONLY_DIRS))
    parser.add_argument('--poll', type=float, default=POLL, metavar='SECONDS')
    parser.add_argument('--version', action='version',
                        version='addon-watch %s' % __version__)
    parser.add_argument('rest', nargs=argparse.REMAINDER,
                        help=argparse.SUPPRESS)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    extra = [a for a in args.rest if a != '--']
    pinned = [m for m in args.modules.split(',') if m]
    extensions = tuple(args.ext) or DEFAULT_EXTENSIONS
    code_only = tuple(args.code_only_dir) or DEFAULT_CODE_ONLY_DIRS

    odoo_bin = find_odoo_bin(args.odoo_bin)
    if not odoo_bin:
        sys.exit("addon-watch: no odoo-bin found. Pass --odoo-bin PATH.")

    roots = [os.path.abspath(p) for p in args.addons]
    missing = [p for p in roots if not os.path.isdir(p)]
    if missing:
        sys.exit("addon-watch: not a directory: %s" % ', '.join(missing))
    if not roots:
        roots = default_roots(args.config, odoo_bin)

    command = [args.python, odoo_bin]
    if args.config:
        command += ['-c', os.path.abspath(args.config)]
    if args.database:
        command += ['-d', args.database]
    command += ['--dev=all'] + extra

    if not can_run_odoo(args.python):
        say(RED, "!! %s cannot import Odoo's dependencies. Pass --python "
                 "PATH for the interpreter Odoo runs on." % args.python)
    say(RESET, 'watching %s for %s'
        % (', '.join(roots), ' '.join(extensions)))
    server = Server(command, cwd=os.path.dirname(odoo_bin))
    state = snapshot(roots, extensions, DEFAULT_SKIP_DIRS)
    server.start(pinned if (pinned and args.upgrade_on_start) else [])

    try:
        while True:
            time.sleep(args.poll)
            if server.returncode is not None:
                # Odoo died on its own. Its traceback is the useful output,
                # so wait for an edit rather than loop on the same failure.
                say(RED, '<< odoo exited (%s); waiting for a change'
                    % server.returncode)
                while True:
                    time.sleep(args.poll)
                    fresh = snapshot(roots, extensions, DEFAULT_SKIP_DIRS)
                    hits = changed(state, fresh)
                    if hits:
                        break
                state = fresh
                server.start(pinned
                             or modules_to_upgrade(hits, roots, code_only))
                continue

            fresh = snapshot(roots, extensions, DEFAULT_SKIP_DIRS)
            hits = changed(state, fresh)
            if not hits:
                continue
            # Let a burst of saves settle before paying for a restart.
            time.sleep(DEBOUNCE)
            fresh = snapshot(roots, extensions, DEFAULT_SKIP_DIRS)
            hits = sorted(set(hits) | set(changed(state, fresh)))
            state = fresh

            upgrade = pinned or modules_to_upgrade(hits, roots, code_only)
            shown = [os.path.basename(p) for p in hits[:4]]
            if len(hits) > 4:
                shown.append('and %d more' % (len(hits) - 4))
            say(YELLOW, '** %s changed%s'
                % (', '.join(shown),
                   ' -> -u %s' % ','.join(upgrade) if upgrade
                   else ' (code only, no upgrade)'))
            server.stop()
            server.start(upgrade)
    except KeyboardInterrupt:
        say(RESET, 'stopping')
    finally:
        server.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
