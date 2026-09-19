import os

import pytest

from addon_watch.cli import default_roots
from addon_watch.watcher import (
    changed,
    is_under,
    module_of,
    modules_to_upgrade,
    read_addons_path,
    snapshot,
)


def make_module(root, name, files=('__manifest__.py',)):
    module = root / name
    for relative in files:
        path = module / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# %s\n' % relative)
    return module


@pytest.fixture
def addons(tmp_path):
    root = tmp_path / 'addons'
    make_module(root, 'sales_extra', (
        '__manifest__.py',
        'models/sale_order.py',
        'views/sale_order_views.xml',
        'controllers/portal.py',
        'tests/test_sale_order.py',
        'static/src/js/widget.js',
    ))
    make_module(root, 'crm_extra', ('__manifest__.py', 'models/lead.py'))
    return root


def test_only_the_watched_extensions_are_seen(addons):
    seen = snapshot([str(addons)])
    names = {os.path.basename(p) for p in seen}
    assert 'sale_order.py' in names
    assert 'sale_order_views.xml' in names
    # static/ is served from disk by Odoo, so a change there is the browser's
    # problem, not a restart.
    assert 'widget.js' not in names


def test_changed_reports_writes_additions_and_deletions():
    before = {'a': 1.0, 'b': 2.0}
    after = {'a': 1.0, 'b': 3.0, 'c': 4.0}
    assert changed(before, after) == ['b', 'c']
    assert changed(after, before) == ['b', 'c']
    assert changed(before, before) == []


def test_a_file_belongs_to_the_module_that_holds_the_manifest(addons):
    name, subpath = module_of(
        str(addons / 'sales_extra' / 'models' / 'sale_order.py'), [str(addons)])
    assert name == 'sales_extra'
    assert subpath == os.path.join('models', 'sale_order.py')


def test_a_file_outside_any_module_belongs_to_none(tmp_path):
    loose = tmp_path / 'notes.py'
    loose.write_text('x = 1\n')
    assert module_of(str(loose), [str(tmp_path)]) == (None, None)


def test_a_view_change_upgrades_its_module(addons):
    paths = [str(addons / 'sales_extra' / 'views' / 'sale_order_views.xml')]
    assert modules_to_upgrade(paths, [str(addons)]) == ['sales_extra']


def test_a_controller_or_test_change_needs_no_upgrade(addons):
    paths = [
        str(addons / 'sales_extra' / 'controllers' / 'portal.py'),
        str(addons / 'sales_extra' / 'tests' / 'test_sale_order.py'),
    ]
    assert modules_to_upgrade(paths, [str(addons)]) == []


def test_only_the_modules_that_changed_are_upgraded(addons):
    paths = [
        str(addons / 'crm_extra' / 'models' / 'lead.py'),
        str(addons / 'sales_extra' / 'controllers' / 'portal.py'),
    ]
    assert modules_to_upgrade(paths, [str(addons)]) == ['crm_extra']


def test_a_manifest_change_upgrades_its_module(addons):
    paths = [str(addons / 'crm_extra' / '__manifest__.py')]
    assert modules_to_upgrade(paths, [str(addons)]) == ['crm_extra']


def test_every_addons_path_entry_is_read(tmp_path):
    (tmp_path / 'addons').mkdir()
    (tmp_path / 'custom').mkdir()
    config = tmp_path / 'odoo.conf'
    config.write_text(
        '[options]\ndb_host = False\naddons_path = addons,custom\n')
    assert read_addons_path(str(config), cwd=str(tmp_path)) == [
        str(tmp_path / 'addons'), str(tmp_path / 'custom')]


def test_a_missing_config_is_not_an_error(tmp_path):
    assert read_addons_path(str(tmp_path / 'nope.conf')) == []


def test_is_under_matches_the_directory_and_its_contents(tmp_path):
    assert is_under(str(tmp_path / 'a' / 'b'), str(tmp_path / 'a'))
    assert is_under(str(tmp_path / 'a'), str(tmp_path / 'a'))
    assert not is_under(str(tmp_path / 'ab'), str(tmp_path / 'a'))


def test_a_relative_addons_path_follows_the_working_directory(tmp_path):
    work = tmp_path / 'work'
    (work / 'custom').mkdir(parents=True)
    config_dir = tmp_path / 'etc'
    config_dir.mkdir()
    config = config_dir / 'odoo.conf'
    config.write_text('[options]\naddons_path = custom\n')
    # Odoo resolves a relative entry against the working directory, so the
    # one that exists there wins over the one beside the config.
    assert read_addons_path(str(config), cwd=str(work)) == [
        str(work / 'custom')]


def test_a_relative_addons_path_falls_back_to_the_config_directory(tmp_path):
    config_dir = tmp_path / 'etc'
    (config_dir / 'custom').mkdir(parents=True)
    config = config_dir / 'odoo.conf'
    config.write_text('[options]\naddons_path = custom\n')
    assert read_addons_path(str(config), cwd=str(tmp_path)) == [
        str(config_dir / 'custom')]


def test_an_absolute_addons_path_is_kept(tmp_path):
    config = tmp_path / 'odoo.conf'
    config.write_text('[options]\naddons_path = /srv/addons\n')
    assert read_addons_path(str(config), cwd=str(tmp_path)) == ['/srv/addons']


def test_custom_addons_inside_the_odoo_tree_are_still_watched(tmp_path):
    # A checkout that keeps its addons beside Odoo's own is a common layout.
    odoo = tmp_path / 'odoo'
    (odoo / 'addons').mkdir(parents=True)
    (odoo / 'odoo' / 'addons').mkdir(parents=True)
    (odoo / 'custom').mkdir()
    odoo_bin = odoo / 'odoo-bin'
    odoo_bin.write_text('#!/usr/bin/env python3\n')
    config = odoo / 'odoo.conf'
    config.write_text('[options]\naddons_path = addons,custom\n')
    assert default_roots(str(config), str(odoo_bin), cwd=str(odoo)) == [
        str(odoo / 'custom')]


def test_without_a_config_the_working_directory_is_watched(tmp_path):
    assert default_roots(None, None, cwd=str(tmp_path)) == [str(tmp_path)]
