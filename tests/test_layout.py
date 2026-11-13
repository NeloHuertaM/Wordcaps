import unittest

from wordcaps.layout import CaptionSettings, Frame, build_clips, split_groups
from wordcaps.srt import parse_srt
from wordcaps.words import Word

FRAME = Frame(fps=30, width=1080, height=1920, start_frame=1000, end_frame=1000 + 30 * 60)
FRAME_AT_ZERO = Frame(fps=30, width=1080, height=1920, start_frame=0, end_frame=9000)


def words_from(spec):
    return [Word(text, start, end) for text, start, end in spec]


def lane_spans(layout):
    return [(c["lane"], c["text"], c["record"], c["record"] + c["duration"]) for c in layout["clips"]]


SENTENCE = words_from([
    ("Esto", 0.0, 0.3), ("es", 0.3, 0.5), ("increíble", 0.5, 1.1), ("de", 1.1, 1.2),
    ("verdad.", 1.2, 1.6), ("Mira", 1.7, 2.0), ("esto", 2.0, 2.3), ("ahora", 2.3, 2.7),
])


class SplitGroupsTests(unittest.TestCase):
    def test_given_more_words_than_the_limit_when_splitting_then_groups_hold_at_most_max_words(self):
        groups = split_groups(SENTENCE, CaptionSettings(max_words=3, split_on_punctuation=False))

        self.assertEqual([len(g) for g in groups], [3, 3, 2])

    def test_given_a_sentence_end_when_splitting_then_the_next_word_starts_a_group(self):
        groups = split_groups(SENTENCE, CaptionSettings(max_words=8, max_chars_per_line=60, max_lines=4))

        self.assertEqual([w.text for w in groups[0]], ["Esto", "es", "increíble", "de", "verdad."])
        self.assertEqual(groups[1][0].text, "Mira")

    def test_given_a_long_pause_when_splitting_then_the_group_breaks_at_the_pause(self):
        words = words_from([("uno", 0, 0.3), ("dos", 0.3, 0.6), ("tres", 2.0, 2.3)])

        groups = split_groups(words, CaptionSettings(max_words=5, pause_split=0.5))

        self.assertEqual([[w.text for w in g] for g in groups], [["uno", "dos"], ["tres"]])

    def test_given_words_that_need_more_lines_than_allowed_when_splitting_then_the_group_breaks(self):
        words = words_from([("palabra", 0, 0.2), ("larguisima", 0.2, 0.4), ("tercera", 0.4, 0.6)])

        groups = split_groups(words, CaptionSettings(max_words=5, max_chars_per_line=10, max_lines=2))

        self.assertEqual([len(g) for g in groups], [2, 1])

    def test_given_single_mode_when_splitting_then_every_word_is_its_own_group(self):
        groups = split_groups(SENTENCE, CaptionSettings(mode="single"))

        self.assertEqual(len(groups), len(SENTENCE))


class BuildClipsTests(unittest.TestCase):
    def test_given_accumulate_mode_when_building_then_each_lane_holds_back_to_back_clips(self):
        layout = build_clips(SENTENCE, CaptionSettings(), FRAME)

        self.assertEqual(lane_spans(layout), [
            (1, "ESTO", 1000, 1033), (2, "ES", 1009, 1033), (3, "INCREÍBLE", 1015, 1033),
            (1, "DE", 1033, 1051), (2, "VERDAD.", 1036, 1051),
            (1, "MIRA", 1051, 1086), (2, "ESTO", 1060, 1086), (3, "AHORA", 1069, 1086),
        ])

    def test_given_a_group_when_building_then_its_words_stay_until_the_next_group_starts(self):
        layout = build_clips(SENTENCE, CaptionSettings(max_words=3, split_on_punctuation=False), FRAME)

        self.assertEqual(lane_spans(layout)[:4], [
            (1, "ESTO", 1000, 1033), (2, "ES", 1009, 1033), (3, "INCREÍBLE", 1015, 1033), (1, "DE", 1033, 1060),
        ])
        self.assertEqual(layout["lanes"], 3)

    def test_given_overlapping_srt_cues_when_building_then_no_clip_starts_inside_the_previous_one_on_its_lane(self):
        srt = (
            "1\n00:00:01,000 --> 00:00:03,000\nhola mundo que tal\n\n"
            "2\n00:00:02,500 --> 00:00:04,000\notra frase aqui\n"
        )

        layout = build_clips(parse_srt(srt), CaptionSettings(), FRAME_AT_ZERO)

        self.assertEqual(lane_spans(layout), [
            (1, "HOLA", 30, 75), (2, "MUNDO", 46, 75), (3, "QUE", 65, 75),
            (1, "OTRA", 75, 106), (2, "TAL", 77, 106), (3, "FRASE", 89, 106),
            (1, "AQUI", 106, 125),
        ])

    def test_given_two_words_in_the_same_frame_in_single_mode_when_building_then_the_one_without_frames_is_dropped(self):
        words = words_from([("uno", 1.0, 1.005), ("dos", 1.01, 1.5)])

        layout = build_clips(words, CaptionSettings(mode="single"), FRAME_AT_ZERO)

        self.assertEqual(lane_spans(layout), [(1, "DOS", 30, 50)])

    def test_given_an_emphasised_word_that_widens_rows_when_building_then_a_group_never_exceeds_max_lines(self):
        words = words_from([("abcdefg", 0, 0.2), ("abcdefgh", 0.2, 0.4), ("abcdefg", 0.4, 0.6)])

        layout = build_clips(words, CaptionSettings(max_words=3, max_lines=2, max_chars_per_line=16), FRAME)

        self.assertEqual([[w["y"] for w in g["words"]] for g in layout["groups"]], [[0.33493, 0.27412], [0.3]])

    def test_given_the_longest_word_when_building_then_it_is_scaled_and_coloured_as_emphasis(self):
        layout = build_clips(SENTENCE, CaptionSettings(max_words=3, split_on_punctuation=False), FRAME)

        increible, esto = layout["clips"][2], layout["clips"][0]
        self.assertEqual(increible["inputs"]["Size"], 0.108)
        self.assertEqual((increible["inputs"]["Red1"], increible["inputs"]["Blue1"]), (1.0, 0.0))
        self.assertEqual(esto["inputs"]["Size"], 0.08)

    def test_given_highlight_active_when_building_then_the_word_switches_to_the_base_colour_when_it_ends(self):
        layout = build_clips(SENTENCE, CaptionSettings(max_words=3, split_on_punctuation=False), FRAME)

        blue = next(k for k in layout["clips"][0]["keys"] if k["input"] == "Blue1")
        self.assertEqual(blue["points"], [[0, 0.0], [8, 0.0], [9, 1.0]])

    def test_given_the_pop_animation_when_building_then_size_is_keyframed_from_zero(self):
        layout = build_clips(SENTENCE, CaptionSettings(animation="pop"), FRAME)

        size_keys = next(k for k in layout["clips"][0]["keys"] if k["input"] == "Size")
        self.assertEqual(size_keys["points"], [[0, 0.0], [3, 0.0944], [6, 0.08]])

    def test_given_single_mode_when_building_then_everything_goes_on_one_centred_lane(self):
        layout = build_clips(SENTENCE[:2], CaptionSettings(mode="single"), FRAME)

        self.assertEqual(layout["lanes"], 1)
        self.assertEqual([c["inputs"]["Center"][0] for c in layout["clips"]], [0.5, 0.5])

    def test_given_words_after_the_timeline_end_when_building_then_they_are_dropped(self):
        short = Frame(fps=30, width=1080, height=1920, start_frame=0, end_frame=30)
        words = words_from([("dentro", 0.1, 0.5), ("fuera", 2.0, 2.4)])

        layout = build_clips(words, CaptionSettings(), short)

        self.assertEqual([c["text"] for c in layout["clips"]], ["DENTRO"])

    def test_given_a_row_when_building_then_its_words_are_centred_and_ordered_left_to_right(self):
        layout = build_clips(SENTENCE[:2], CaptionSettings(), FRAME)

        self.assertEqual([c["inputs"]["Center"] for c in layout["clips"]], [[0.4384, 0.3], [0.6112, 0.3]])

    def test_given_measured_glyph_widths_when_building_then_words_are_spaced_by_them(self):
        settings = CaptionSettings(glyph_widths={"E": 0.8, "S": 0.8, "T": 0.8, "O": 0.8, " ": 0.25}, max_words=2)

        layout = build_clips(SENTENCE[:2], settings, FRAME)

        self.assertEqual([c["inputs"]["Center"][0] for c in layout["clips"]], [0.426, 0.638])

    def test_given_two_rows_when_building_then_the_second_row_is_lower(self):
        words = words_from([("primera", 0, 0.3), ("segunda", 0.3, 0.6)])

        layout = build_clips(words, CaptionSettings(max_chars_per_line=8, max_words=2), FRAME)

        self.assertEqual([c["inputs"]["Center"][1] for c in layout["clips"]], [0.32588, 0.26507])

    def test_given_my_keyword_list_when_building_then_matches_ignore_case_and_punctuation(self):
        words = words_from([("¡Dinero!", 0, 0.5), ("gratis", 0.5, 1.0)])
        settings = CaptionSettings(emphasis="keywords", keywords=["DINERO"])

        layout = build_clips(words, settings, FRAME)

        self.assertEqual([c["inputs"]["Size"] for c in layout["clips"]], [0.108, 0.08])

    def test_given_no_emphasis_when_building_then_the_longest_word_keeps_the_base_size(self):
        layout = build_clips(SENTENCE[:3], CaptionSettings(emphasis="none"), FRAME)

        self.assertEqual([c["inputs"]["Size"] for c in layout["clips"]], [0.08, 0.08, 0.08])

    def test_given_strip_punctuation_when_building_then_punctuation_goes_unless_nothing_would_remain(self):
        words = words_from([("¿Qué", 0, 0.5), ("...", 0.5, 1.0)])

        layout = build_clips(words, CaptionSettings(strip_punctuation=True, split_on_punctuation=False), FRAME)

        self.assertEqual([c["text"] for c in layout["clips"]], ["QUÉ", "..."])

    def test_given_uppercase_disabled_when_building_then_the_text_keeps_its_case(self):
        layout = build_clips(SENTENCE[:2], CaptionSettings(uppercase=False), FRAME)

        self.assertEqual([c["text"] for c in layout["clips"]], ["Esto", "es"])

    def test_given_highlight_disabled_or_single_mode_when_building_then_only_size_is_keyframed(self):
        for settings in (CaptionSettings(highlight_active=False), CaptionSettings(mode="single")):
            with self.subTest(mode=settings.mode, highlight=settings.highlight_active):
                layout = build_clips(SENTENCE[:2], settings, FRAME)
                self.assertEqual([k["input"] for k in layout["clips"][0]["keys"]], ["Size"])
                self.assertEqual(layout["clips"][0]["inputs"]["Blue1"], 1.0)

    def test_given_a_timeline_with_zero_fps_when_reading_it_then_it_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "a cero"):
            Frame.from_timeline({"fps": 0, "width": 1920, "height": 1080, "startFrame": 0, "endFrame": 10})

    def test_given_outline_disabled_when_building_then_no_outline_inputs_are_sent(self):
        layout = build_clips(SENTENCE, CaptionSettings(outline=False), FRAME)

        self.assertNotIn("Enabled2", layout["clips"][0]["inputs"])


class SettingsTests(unittest.TestCase):
    def test_given_unknown_keys_when_parsing_then_they_are_ignored(self):
        settings = CaptionSettings.from_dict({"max_words": 4, "unknown": 1})

        self.assertEqual(settings.max_words, 4)

    def test_given_invalid_values_when_parsing_then_a_value_error_names_the_problem(self):
        invalid = ({"mode": "x"}, {"animation": "spin"}, {"color": "red"}, {"clip_color": "Red"}, {"size": 2},
                   {"hold_seconds": None}, {"zone_width": "x"}, {"max_words": True})
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                CaptionSettings.from_dict(data)


if __name__ == "__main__":
    unittest.main()
