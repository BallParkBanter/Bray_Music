"""Tests for _extract_genre() compound and standard genre detection."""

import pytest
from main import _extract_genre


class TestCompoundGenres:
    """Compound genres must be detected before their single-word components."""

    def test_country_rock(self):
        assert _extract_genre("Country rock song about a bonfire") == "country rock"

    def test_southern_rock(self):
        assert _extract_genre("Southern rock anthem about the highway") == "country rock"

    def test_latin_pop(self):
        assert _extract_genre("Latin pop song about dancing under the stars") == "latin pop"

    def test_kpop_hyphen(self):
        assert _extract_genre("K-pop inspired song about a crush") == "k-pop"

    def test_kpop_no_hyphen(self):
        assert _extract_genre("Kpop song about summer") == "k-pop"

    def test_jpop_hyphen(self):
        assert _extract_genre("J-pop song about school life") == "j-pop"

    def test_anime(self):
        assert _extract_genre("Anime opening theme about friendship") == "j-pop"


class TestStandardGenres:
    """Standard single-word genres must still work after compound genre changes."""

    def test_rock(self):
        assert _extract_genre("Rock song about fighting demons") == "rock"

    def test_pop(self):
        assert _extract_genre("Pop song about a summer romance") == "pop"

    def test_hip_hop(self):
        assert _extract_genre("Rap song about growing up") == "hip hop"

    def test_jazz(self):
        assert _extract_genre("Jazz lounge song about rain") == "jazz"

    def test_blues(self):
        assert _extract_genre("Blues song about Monday morning") == "blues"

    def test_country(self):
        assert _extract_genre("Country ballad about a truck driver") == "country"

    def test_metal(self):
        assert _extract_genre("Metal song about Vikings") == "metal"

    def test_punk(self):
        assert _extract_genre("Punk rock song about rebellion") == "punk"

    def test_folk(self):
        assert _extract_genre("Folk song about a fishing boat") == "folk"

    def test_gospel(self):
        assert _extract_genre("Gospel song about grace") == "gospel"

    def test_soul(self):
        assert _extract_genre("Soul song about a mothers love") == "soul"

    def test_reggae(self):
        assert _extract_genre("Reggae song about Sunday") == "reggae"

    def test_electronic(self):
        assert _extract_genre("Electronic dance track") == "electronic"

    def test_indie(self):
        assert _extract_genre("Indie rock song about a road trip") == "indie"

    def test_ballad(self):
        assert _extract_genre("Acoustic love song about growing old") == "ballad"

    def test_classical(self):
        assert _extract_genre("Classical orchestral piece") == "classical"

    def test_rnb(self):
        assert _extract_genre("R&B slow jam about love") == "r&b"


class TestFallback:
    """Unknown descriptions should return 'music'."""

    def test_no_genre(self):
        assert _extract_genre("A song about something") == "music"

    def test_empty(self):
        assert _extract_genre("") == "music"

    def test_random_text(self):
        assert _extract_genre("The quick brown fox jumps") == "music"
