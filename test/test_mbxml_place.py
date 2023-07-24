# Tests for parsing of place results

import unittest
import os
from test import _common


class PlaceTest(unittest.TestCase):
    def setUp(self):
        self.datadir = os.path.join(os.path.dirname(__file__), "data", "place")

    def testPlace(self):
        filename = "0c79cdbb-acd6-4e30-aaa3-a5c8d6b36a48_inc=aliases_tags.xml"
        res = _common.open_and_parse_test_data(self.datadir, filename)

        p = res["place"]
        self.assertEqual("All Saints’ Church", p["name"])
        self.assertEqual("East Finchley, Durham Road", p["disambiguation"])
        self.assertEqual("38 Durham Road, London N2 9DP, United Kingdom", p["address"])
        self.assertEqual({"latitude": "51.591812", "longitude": "-0.159699"}, p["coordinates"])
        self.assertEqual("f03d09b3-39dc-4083-afd6-159e3f0d462f", p["area"]["id"])
        self.assertEqual("1891", p["life-span"]["begin"])
        self.assertEqual("All Saints' Durham Road", p["alias-list"][0]["alias"])
        self.assertEqual("type=church", p["tag-list"][0]["name"])
        self.assertEqual("1", p["tag-list"][0]["count"])

    def testListFromBrowse(self):
        filename = "_area=f1724242-d9e8-40bd-a1d6-2add4b0c24ec&inc=annotation.xml"
        res = _common.open_and_parse_test_data(self.datadir, filename)

        self.assertEqual(21, res["place-count"])
        self.assertEqual(21, len(res["place-list"]))
        self.assertTrue(res["place-list"][13]["annotation"]["text"].startswith("the \"Columbia Studios\" it was"))
