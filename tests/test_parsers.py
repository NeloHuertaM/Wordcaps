import unittest

from wordcaps.animations import size_keys
from wordcaps.lua_literal import to_lua
from wordcaps.srt import BYTE_ORDER_MARK, parse_srt
from wordcaps.whisper import parse_whisper_json

SRT = BYTE_ORDER_MARK + """1
00:00:01,000 --> 00:00:02,000
<i>Hola</i> mundo

2
00:00:03,500 --> 00:00:04,500
¿Qué tal?
"""


class SrtTests(unittest.TestCase):
    def test_given_cues_when_parsing_then_each_word_gets_a_share_of_its_cue(self):
        words = parse_srt(SRT)

        self.assertEqual([w.text for w in words], ["Hola", "mundo", "¿Qué", "tal?"])
        self.assertEqual(words[0].start, 1.0)
        self.assertAlmostEqual(words[1].end, 2.0, places=2)
        self.assertEqual(words[2].start, 3.5)

    def test_given_text_without_timings_when_parsing_then_no_words_come_back(self):
        self.assertEqual(parse_srt("esto no es un srt"), [])


class WhisperParseTests(unittest.TestCase):
    def test_given_word_segments_when_parsing_then_punctuation_joins_the_previous_word(self):
        data = {"transcription": [
            {"offsets": {"from": 0, "to": 400}, "text": " Hola"},
            {"offsets": {"from": 400, "to": 420}, "text": ","},
            {"offsets": {"from": 420, "to": 900}, "text": " amigos"},
            {"offsets": {"from": 900, "to": 1500}, "text": " [BLANK_AUDIO]"},
            {"offsets": {"from": 1500, "to": 1500}, "text": " ya"},
        ]}

        words = parse_whisper_json(data)

        self.assertEqual([w.text for w in words], ["Hola,", "amigos", "ya"])
        self.assertEqual(words[0].end, 0.42)
        self.assertGreater(words[2].end, words[2].start)


class LuaLiteralTests(unittest.TestCase):
    def test_given_nested_values_when_encoding_then_strings_are_escaped_byte_by_byte(self):
        encoded = to_lua({"a": [1, 2.5, True, None], "t": 'é"\\'})

        self.assertEqual(encoded, '{["a"]={1,2.5,true,nil},["t"]="\\195\\169\\034\\092"}')

    def test_given_a_non_finite_number_when_encoding_then_it_is_rejected(self):
        with self.assertRaises(ValueError):
            to_lua(float("nan"))


class AnimationTests(unittest.TestCase):
    def test_given_a_short_clip_when_keying_then_the_curve_is_squeezed_inside_it(self):
        points = size_keys("bounce", 0.1, 5)

        self.assertEqual(points, [[0, 0.0], [1, 0.13], [3, 0.09], [4, 0.1]])

    def test_given_no_animation_when_keying_then_there_are_no_keys(self):
        self.assertEqual(size_keys("none", 0.1, 30), [])


if __name__ == "__main__":
    unittest.main()
