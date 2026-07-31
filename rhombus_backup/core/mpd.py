"""Parse Rhombus MPEG-DASH MPD documents (port of the original rhombus_mpd_info.py,
stdlib-only - no xmltodict dependency)."""
import re
import xml.etree.ElementTree as ET


class RhombusMPDInfo:
    """Segment layout of a Rhombus MPD document.

    segment_pattern: e.g. "seg_$Number$.m4v" - replace $Number$ with the index
    init_string:     e.g. "seg_init.mp4"
    start_index:     first segment number (0 for LAN streams, 1 for WAN)
    """

    def __init__(self, raw_doc: str, audio: bool):
        raw_doc = re.sub(r'xmlns="[^"]+"', "", raw_doc, count=1)
        root = ET.fromstring(raw_doc)
        if audio:
            template = root.find("./Period/AdaptationSet/Representation/SegmentTemplate")
        else:
            template = root.find("./Period/AdaptationSet/SegmentTemplate")
        if template is None:
            raise ValueError("MPD document has no SegmentTemplate")
        self.segment_pattern = template.attrib["media"]
        self.init_string = template.attrib["initialization"]
        self.start_index = int(template.attrib["startNumber"])

    def segment_name(self, index: int) -> str:
        return self.segment_pattern.replace("$Number$", str(index + self.start_index))


URI_FILE_ENDINGS = ["clip.mpd", "file.mpd"]


def segment_uri(mpd_uri: str, segment_name: str) -> str:
    """Swap the trailing mpd filename for a segment filename."""
    for ending in URI_FILE_ENDINGS:
        if ending in mpd_uri:
            return mpd_uri.replace(ending, segment_name)
    raise ValueError("Unrecognized MPD URI format: does not end in clip.mpd/file.mpd")
