import json
from collections import Counter

from xmdm import (
  Material,
  available_materials,
  database_directory,
  load_index,
  load_record,
  validate_record_data,
)


def test_public_material_alias_and_bundled_database():
  assert Material is Material
  assert 'a-Si' not in available_materials()
  assert 'Si' in available_materials()
  assert database_directory().name == 'xmdm-db'

  material = Material.from_db('Si/a-Si-H', verbose=False)
  assert material.name == 'silicon (Si)'
  assert material.f.size > 0


def test_all_bundled_records_load_and_validate():
  _, index = load_index()
  for material_id, entry in index['materials'].items():
    for reference in entry['records']:
      record, _ = load_record(
        f'{material_id}/{reference["name"]}',
        reference['model'],
      )
      physics = 'nlo' if record['data'].get('type') == 'n2' else 'optics'
      assert record['physics'] == reference['physics'] == physics
      validate_record_data(record)


def test_all_bundled_record_files_have_matching_physics():
  for path in database_directory().glob('*/*.json'):
    record = json.loads(path.read_text(encoding='utf-8'))
    physics = 'nlo' if record['data'].get('type') == 'n2' else 'optics'
    assert record['physics'] == physics, str(path)


def test_refractiveindex_records_have_trimmed_metadata():
  root, index = load_index()
  checked = 0
  for material in index['materials'].values():
    for reference in material['records']:
      record = json.loads((root / reference['path']).read_text(encoding='utf-8'))
      metadata = record['metadata']
      if 'downloaded from refractiveindex.info' not in metadata.get('source', ''):
        continue
      assert not {
        'refractiveindex_entry_type', 'database', 'source_reference',
      }.intersection(metadata)
      assert not any(key.startswith('database_') for key in metadata)
      assert not any(key.startswith('database_') for key in reference)
      assert 'legacy_path' not in metadata
      checked += 1
  assert checked == 1384


def test_bundled_catalog_has_consistent_provenance_and_no_orphan_files():
  root, index = load_index()
  paths = set()
  ids = set()
  counts = Counter()
  for material in index['materials'].values():
    for reference in material['records']:
      assert reference['path'] not in paths
      assert reference['id'] not in ids
      paths.add(reference['path'])
      ids.add(reference['id'])
      record = json.loads((root / reference['path']).read_text(encoding='utf-8'))
      metadata = record['metadata']
      source = metadata.get('source', '')
      assert reference.get('source', '') == source
      counts[record['physics']] += 1
      if 'downloaded from Lumerical' in source:
        counts['lumerical'] += 1
        assert 'legacy_path' in metadata
        assert 'refractive' not in json.dumps(metadata).lower()
      if 'measured at POSTECH' in source:
        counts['postech'] += 1
        assert 'Measured by' in source
        assert 'refractive' not in json.dumps(metadata).lower()
        assert 'Lumerical' not in source
  assert paths == {
    path.relative_to(root).as_posix() for path in root.glob('*/*.json')
  }
  assert len(paths) == 1472
  assert counts == {'optics': 1265, 'nlo': 207, 'lumerical': 62, 'postech': 5}


def test_upstream_records_replace_legacy_equivalent_formats():
  silver, _ = load_record('Ag/Johnson', 'tabulated')
  assert silver['data']['unit'] == 'um'
  assert silver['data']['type'] == 'nk'
  assert silver['data']['f'][0] == 0.1879
  assert silver['data']['re'][0] == 1.07
  assert silver['data']['im'][0] == 1.212

  for selector, model in [
    ('CdSe/Bond-o', 'tabulated'),
    ('CdS/Ninomiya-e', 'tabulated'),
    ('GaN/Kawashima', 'tabulated'),
    ('ZnO/Bond-o', 'rii_formula'),
    ('Si3N4/Luke', 'rii_formula'),
    ('Si/Pierce', 'tabulated'),
    ('PDMS/Zhang-10-1', 'tabulated'),
  ]:
    record, _ = load_record(selector, model)
    assert 'downloaded from refractiveindex.info' in record['metadata']['source']
    assert 'legacy_path' not in record['metadata']
