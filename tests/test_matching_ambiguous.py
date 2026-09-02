"""Regression: match_name must not silently pick one of several ambiguous matches.

The token fallback accepted the FIRST index entry whose key contained all the
nickname tokens. With a short/common nickname ("Pedro", "Álvarez") several players
match and it returned an arbitrary one — a false positive that SANITY_MAX_DIFF in
flip.py then has to paper over. An ambiguous token match must resolve to None; the
real fix (an ID crosswalk) builds on top of a matcher that no longer lies.
"""

import unittest

from fantasybot.matching import index_by_name, match_name


class TestAmbiguousMatch(unittest.TestCase):
    def test_ambiguous_token_match_is_rejected(self):
        index = index_by_name([{"nombre": "pedro porro", "v": 1},
                               {"nombre": "pedro leon", "v": 2}])
        # "Pedro" alone matches BOTH keys -> must not pick one at random
        self.assertIsNone(match_name("Pedro", "", index))

    def test_unique_token_match_still_works(self):
        index = index_by_name([{"nombre": "karl etta eyong", "v": 1},
                               {"nombre": "pedro porro", "v": 2}])
        # "Etta Eyong" matches exactly one key -> still resolved
        self.assertEqual(match_name("Etta Eyong", "", index)["v"], 1)

    def test_short_token_needs_a_whole_word(self):
        # "oso" is inside cardOSO and OSOrio but is neither man's name
        index = index_by_name([{"nombre": "johnny cardoso", "v": 1},
                               {"nombre": "abiel osorio", "v": 2}])
        self.assertIsNone(match_name("Oso", "", index))
        self.assertEqual(match_name("Oso", "", index_by_name(
            [{"nombre": "joaquin oso", "v": 3}]))["v"], 3)

    def test_abbreviations_are_prefixes(self):
        index = index_by_name([{"nombre": "javier hernandez", "v": 1},
                               {"nombre": "adria altimira", "v": 2},
                               {"nombre": "adria pedrosa", "v": 3},
                               {"nombre": "pedro bigas", "v": 4}])
        self.assertEqual(match_name("Javi Hernández", "", index)["v"], 1)
        self.assertEqual(match_name("A. Alti", "", index)["v"], 2)
        # a surname is not an abbreviation of a shorter first name
        self.assertEqual(match_name("Pedrosa", "", index)["v"], 3)
        # "Pedro" is both a whole word and a prefix of pedrosa: ambiguous
        self.assertIsNone(match_name("Pedro", "", index))

    def test_initials_must_agree_with_the_key(self):
        index = index_by_name([{"nombre": "david jimenez", "v": 1},
                               {"nombre": "isra dominguez", "v": 2},
                               {"nombre": "johnny cardoso", "v": 3},
                               {"nombre": "alberto moleiro", "v": 4}])
        self.assertEqual(match_name("D. Jiménez", "", index)["v"], 1)
        self.assertIsNone(match_name("J. David", "", index))
        self.assertIsNone(match_name("C. Dominguez", "", index))
        self.assertEqual(match_name("John C.", "", index)["v"], 3)
        self.assertIsNone(match_name("Alberto F.", "", index))

    def test_initials_are_ignored_when_the_key_has_no_spare_word(self):
        index = index_by_name([{"nombre": "terrats", "v": 1},
                               {"nombre": "pathe ciss", "v": 2}])
        self.assertEqual(match_name("R. Terrats", "", index)["v"], 1)
        self.assertEqual(match_name("Pathé I. Ciss", "", index)["v"], 2)
        # a two-word key still has to account for the initial
        self.assertIsNone(match_name("J. David Jimenez", "",
                                     index_by_name([{"nombre": "david jimenez"}])))

    def test_several_initials_keep_their_order(self):
        index = index_by_name([{"nombre": "carlos david smith", "v": 1},
                               {"nombre": "smith david carlos", "v": 2}])
        self.assertIsNone(match_name("D. C. Smith", "", index))
        self.assertEqual(match_name("C. D. Smith", "", index)["v"], 1)
        self.assertIsNone(match_name("Smith C. D.", "", index))
        self.assertEqual(match_name("Smith D. C.", "", index)["v"], 2)


if __name__ == "__main__":
    unittest.main()
