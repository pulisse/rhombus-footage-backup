import pytest

from rhombus_backup.core.mpd import RhombusMPDInfo, segment_uri

VIDEO_MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <SegmentTemplate media="seg_$Number$.m4v" initialization="seg_init.mp4"
                       startNumber="0" duration="2" timescale="1"/>
      <Representation id="v0" codecs="avc1"/>
    </AdaptationSet>
  </Period>
</MPD>"""

AUDIO_MPD = """<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period>
    <AdaptationSet mimeType="audio/mp4">
      <Representation id="a0" codecs="mp4a">
        <SegmentTemplate media="aseg_$Number$.m4a" initialization="aseg_init.mp4"
                         startNumber="1" duration="2" timescale="1"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""


def test_parse_video_mpd_lan():
    info = RhombusMPDInfo(VIDEO_MPD, audio=False)
    assert info.init_string == "seg_init.mp4"
    assert info.start_index == 0
    assert info.segment_name(0) == "seg_0.m4v"
    assert info.segment_name(5) == "seg_5.m4v"


def test_parse_audio_mpd_wan_start_index():
    info = RhombusMPDInfo(AUDIO_MPD, audio=True)
    assert info.start_index == 1
    assert info.segment_name(0) == "aseg_1.m4a"   # WAN streams start at 1


def test_segment_uri_replaces_mpd_filename():
    uri = "https://cam.local/media/clip.mpd?x=1"
    assert segment_uri(uri, "seg_9.m4v") == "https://cam.local/media/seg_9.m4v?x=1"
    uri2 = "https://cam.local/media/file.mpd"
    assert segment_uri(uri2, "seg_init.mp4") == "https://cam.local/media/seg_init.mp4"


def test_segment_uri_rejects_unknown_format():
    with pytest.raises(ValueError):
        segment_uri("https://cam.local/media/other.mpd", "seg_1.m4v")
