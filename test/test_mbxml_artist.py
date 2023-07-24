# Tests for parsing of artist queries

import unittest
import os
from test import _common


class GetArtistTest(unittest.TestCase):
    def setUp(self):
        self.datadir = os.path.join(os.path.dirname(__file__), "data", "artist")

    def testArtistAliases(self):
        res = _common.open_and_parse_test_data(self.datadir, "0e43fe9d-c472-4b62-be9e-55f971a023e1_inc=aliases.xml")
        aliases = res["artist"]["alias-list"]
        self.assertEqual(len(aliases), 34)

        a0 = aliases[0]
        self.assertEqual(a0["alias"], "Prokefiev")
        self.assertEqual(a0["sort-name"], "Prokefiev")

        a15 = aliases[15]
        self.assertEqual(a15["alias"], "Sergei Prokofiev")
        self.assertEqual(a15["sort-name"], "Prokofiev, Sergei")
        self.assertEqual(a15["locale"], "en")
        self.assertEqual(a15["primary"], "primary")

        res = _common.open_and_parse_test_data(self.datadir, "2736bad5-6280-4c8f-92c8-27a5e63bbab2_inc=aliases.xml")
        self.assertFalse("alias-list" in res["artist"])
    
    def testArtistTargets(self):
        res = _common.open_and_parse_test_data(self.datadir, "b3785a55-2cf6-497d-b8e3-cfa21a36f997_inc=artist-rels.xml")
        self.assertTrue('target-credit' in res['artist']['artist-relation-list'][0])
        self.assertEqual(res['artist']['artist-relation-list'][0]["target-credit"], "LUHAN")
