from neobot.models.message import MessageSegment
from neobot.models.objects import GroupInfo, StrangerInfo

class TestMessageSegment:
    def test_text_segment(self):
        seg = MessageSegment.text("Hello")
        assert seg.type == "text"
        assert seg.data["text"] == "Hello"
        assert str(seg) == "Hello"
        assert seg.plain_text == "Hello"

    def test_at_segment(self):
        seg = MessageSegment.at(123456)
        assert seg.type == "at"
        assert seg.data["qq"] == "123456"
        assert str(seg) == "[CQ:at,qq=123456]"
        assert seg.is_at(123456) is True
        assert seg.is_at(654321) is False
        assert seg.is_at() is True

    def test_image_segment(self):
        seg = MessageSegment.image("http://example.com/img.jpg", cache=False, proxy=False)
        assert seg.type == "image"
        assert seg.data["file"] == "http://example.com/img.jpg"
        assert str(seg) == "[CQ:image,file=http://example.com/img.jpg,cache=0,proxy=0]"
        assert seg.image_url == ""

    def test_face_segment(self):
        seg = MessageSegment.face(123)
        assert seg.type == "face"
        assert seg.data["id"] == "123"
        assert str(seg) == "[CQ:face,id=123]"

    def test_reply_segment(self):
        seg = MessageSegment.reply(1001)
        assert seg.type == "reply"
        assert seg.data["id"] == "1001"
        assert str(seg) == "[CQ:reply,id=1001]"

    def test_add_segments(self):
        seg1 = MessageSegment.text("Hello ")
        seg2 = MessageSegment.at(123)
        combined = seg1 + seg2
        assert isinstance(combined, list)
        assert len(combined) == 2
        assert combined[0] == seg1
        assert combined[1] == seg2

    def test_add_segment_and_string(self):
        seg = MessageSegment.at(123)
        combined = seg + " Hello"
        assert isinstance(combined, list)
        assert len(combined) == 2
        assert combined[0] == seg
        assert combined[1].type == "text"
        assert combined[1].data["text"] == " Hello"

    def test_add_string_and_segment(self):
        seg = MessageSegment.at(123)
        combined = "Hello " + seg
        assert isinstance(combined, list)
        assert len(combined) == 2
        assert combined[0].type == "text"
        assert combined[0].data["text"] == "Hello "
        assert combined[1] == seg

    def test_share_segment(self):
        seg = MessageSegment.share("http://example.com", "Title", "Content", "http://example.com/img.jpg")
        assert seg.type == "share"
        assert seg.data["url"] == "http://example.com"
        assert seg.share_url == "http://example.com"
        assert str(seg) == "[CQ:share,url=http://example.com,title=Title,content=Content,image=http://example.com/img.jpg]"

    def test_music_segment(self):
        seg = MessageSegment.music("qq", "123456")
        assert seg.type == "music"
        assert seg.data["type"] == "qq"
        assert seg.data["id"] == "123456"
        assert seg.music_url == ""

    def test_music_custom_segment(self):
        seg = MessageSegment.music_custom("http://example.com", "http://example.com/audio.mp3", "Title", "Content", "http://example.com/img.jpg")
        assert seg.type == "music"
        assert seg.data["type"] == "custom"
        assert seg.music_url == "http://example.com"
        assert str(seg) == "[CQ:music,type=custom,url=http://example.com,audio=http://example.com/audio.mp3,title=Title,content=Content,image=http://example.com/img.jpg]"

    def test_record_segment(self):
        seg = MessageSegment.record("http://example.com/audio.mp3", magic=True, cache=False, proxy=False)
        assert seg.type == "record"
        assert seg.data["file"] == "http://example.com/audio.mp3"
        assert seg.data["magic"] == "1"
        assert seg.file_url == "http://example.com/audio.mp3"
        assert str(seg) == "[CQ:record,file=http://example.com/audio.mp3,magic=1,cache=0,proxy=0]"

    def test_video_segment(self):
        seg = MessageSegment.video("http://example.com/video.mp4", "http://example.com/cover.jpg")
        assert seg.type == "video"
        assert seg.data["file"] == "http://example.com/video.mp4"
        assert seg.data["cover"] == "http://example.com/cover.jpg"
        assert seg.file_url == "http://example.com/video.mp4"
        assert str(seg) == "[CQ:video,file=http://example.com/video.mp4,c=2,cover=http://example.com/cover.jpg]"

    def test_file_segment(self):
        seg = MessageSegment.file("http://example.com/file.txt")
        assert seg.type == "file"
        assert seg.data["file"] == "http://example.com/file.txt"
        assert seg.file_url == "http://example.com/file.txt"
        assert str(seg) == "[CQ:file,file=http://example.com/file.txt]"

    def test_rps_segment(self):
        seg = MessageSegment.rps()
        assert seg.type == "rps"
        assert str(seg) == "[CQ:rps]"

    def test_dice_segment(self):
        seg = MessageSegment.dice()
        assert seg.type == "dice"
        assert str(seg) == "[CQ:dice]"

    def test_shake_segment(self):
        seg = MessageSegment.shake()
        assert seg.type == "shake"
        assert str(seg) == "[CQ:shake]"

    def test_anonymous_segment(self):
        seg = MessageSegment.anonymous(ignore=True)
        assert seg.type == "anonymous"
        assert seg.data["ignore"] == "1"
        assert str(seg) == "[CQ:anonymous,ignore=1]"

    def test_contact_segment(self):
        seg = MessageSegment.contact("qq", 123456)
        assert seg.type == "contact"
        assert seg.data["type"] == "qq"
        assert seg.data["id"] == "123456"
        assert str(seg) == "[CQ:contact,type=qq,id=123456]"

    def test_location_segment(self):
        seg = MessageSegment.location(39.9042, 116.4074, "Beijing", "China")
        assert seg.type == "location"
        assert seg.data["lat"] == "39.9042"
        assert seg.data["lon"] == "116.4074"
        assert str(seg) == "[CQ:location,lat=39.9042,lon=116.4074,title=Beijing,content=China]"

    def test_json_segment(self):
        seg = MessageSegment.json('{"key": "value"}')
        assert seg.type == "json"
        assert seg.data["data"] == '{"key": "value"}'
        assert str(seg) == "[CQ:json,data={\"key\": \"value\"}]"

    def test_xml_segment(self):
        seg = MessageSegment.xml('<xml>Hello</xml>')
        assert seg.type == "xml"
        assert seg.data["data"] == '<xml>Hello</xml>'
        assert str(seg) == "[CQ:xml,data=<xml>Hello</xml>]"

    def test_repr(self):
        seg = MessageSegment.text("Hello")
        assert repr(seg) == "[MS:text:{'text': 'Hello'}]"

class TestObjects:
    def test_group_info(self):
        data = {
            "group_id": 123456,
            "group_name": "Test Group",
            "member_count": 10,
            "max_member_count": 100
        }
        group = GroupInfo(**data)
        assert group.group_id == 123456
        assert group.group_name == "Test Group"

    def test_stranger_info(self):
        data = {
            "user_id": 111111,
            "nickname": "Stranger",
            "sex": "male",
            "age": 18
        }
        user = StrangerInfo(**data)
        assert user.user_id == 111111
        assert user.nickname == "Stranger"
