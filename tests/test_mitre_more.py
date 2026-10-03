"""MITRE more."""
from toxindb import mitre


def test_mitre_unknown():
    m = mitre.map_to_atlas('TX-999')
    assert m['technique'] == 'AML.UNKNOWN'
