import time
import tarfile
import uuid
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from os import SEEK_END
from typing import BinaryIO

KNOWN_NAMES: dict[bytes, str] = {
    # "Name"
    # "Location"
    # "Type"
    # "FileType"
    # "Slot"
    # "AccountReference"
    # "IsAutosave"
    # "IsQuicksave"
    # "IsPrevious"
    # "IsDirectory"
    # "Path"
    b'\xbb\x5e\x30\x88': "EnabledMods",
    b'\x5c\xae\x27\x84': "RequiredMods",
    # b'\xd8@\xe5\xf4': "Id"
    # "Title"
    # "SubscriptionId"
    b'\xda\x45\x05\x3a': "SavedByVersion",
    b'\xb0\x13\x4c\x1e': "DisplayName",
    b'\x64\x6d\xfe\x0e': "SaveTime",
    # "DisplaySaveTime"
    b'\xbb\xe4\x9a\xaf': "HostCivilization",
    b'\x2a\x63\x0a\x76': "HostCivilizationName",
    b'\xa1\xb2\xb7\x6b': "HostLeader",
    b'\x95\xda\xbc\x9d': "HostLeaderName",
    b'\x15\x87\x98\x85': "HostForegroundColorValue",
    b'\x81\x6f\x54\x7c': "HostBackgroundColorValue",
    b'\xa8\x16\xb4\x7f': "HostDifficulty",
    b'\x1d\xe7\x32\x0f': "HostDifficultyName",
    b'\x55\x0e\x17\xe7': "HostEra",
    b'\xf3\x2f\xf5\x12': "HostEraName",
    # "StartEra"
    # "StartEraName"
    # "GameType"
    # "StartingMajorPlayerCount"
    # "StartingMinorPlayerCount"
    # "StartingTurn"
    b'\x9d\x2c\xe6\xbd': "CurrentTurn",
    b'\x99\xb0\xd9\x05': "GameSpeed",
    b'\xc3\xd4\xd3\xfa': "GameSpeedName",
    b'\x40\x5c\x83\x0b': "MapSize",
    b'\xcd\x93\x9b\xa6': "MapSizeName",
    b'\x5a\x87\xd8\x63': "MapScript",
    b'\x27\x60\x4c\x58': "MapScriptName",
    b'\xde\x25\x59\xc4': "Ruleset",
    b'\x31\xa4\x28\xd0': "RulesetName",
    # "ScenarioName"
    # "ScenarioDescription"
    # "TunerActive"
    # "EnabledGameModes"
    # b'\00\ff\00\ff': "GameChallengeUuid"


    # Mod object entries
    b'\x54\x5f\xc4\x04': "Id",
    b'\x72\xe1\x34\x30': "Name",
    b'\x92\xf5\xb0\x6d': "SubscriptionId",

    # Official names for sections unknown for now
    b'\xf9\x37\x6f\x30': "PLATFORM",
    b'\xc8\xd1\x8c\x1b': "MOD_BLOCK_2",
    b'\x44\x7f\xd4\xfe': "MOD_BLOCK_3",
}


def _parse_int32(input_buffer: BinaryIO) -> int:
    return int.from_bytes(input_buffer.read(4), byteorder="little", signed=False)


def _to_bytes(x: int) -> bytes:
    return x.to_bytes(length=4, byteorder="little", signed=False)


@dataclass
class Marker:
    name: bytes
    type_: int

    def serialize(self) -> bytes:
        return name + _to_bytes(self.type_)

    def pretty_str(self) -> str:
        return f"[[{KNOWN_NAMES.get(self.name, f'{self.name}')}, {hex(self.type_)}]]"


@dataclass(kw_only=True)
class GameElement(ABC):
    marker: Marker

    @abstractmethod
    def serialize(self) -> bytes:
        """Serialized bytestring, as it appeared in the original .civ6save"""
        ...

    @abstractmethod
    def serialize_uncompressed(self) -> bytes:
        """Uncompressed content, to be stored in final gzip"""
        ...

    @abstractmethod
    def pretty_str(self) -> str:
        """Debug str that's ~= 80 char long"""
        ...


@dataclass(kw_only=True)
class IntElement(GameElement):
    """32-bit integer"""
    value: int

    def serialize(self) -> bytes:
        return self.header.serialize() + (b'\0' * 8) + _to_bytes(self.value)

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"IntElement( {self.marker.pretty_str()}, value={self.value} (or {hex(self.value)}) )"


@dataclass
class ByteData:
    b: bytes
    b_per_element: int

    def serialize(self) -> bytes:
        return ((len(b) // b_per_element).to_bytes(3, "little", signed=False) +
                b"\x21" + _to_bytes(self.b_per_element) + self.b)

    def pretty_str(self) -> str:
        return


@dataclass(kw_only=True)
class UnknownStringElement(GameElement):
    """Unknown string type, always "0 length", always 4 zero bytes"""
    header: bytes

    def serialize(self) -> bytes:
        return self.marker.serialize() + self.header + b'\0\0\0\0'

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"UnknownString( {self.marker}, header={self.header} )"


@dataclass(kw_only=True)
class StringElement(GameElement):
    """Raw ASCII string"""
    content: ByteData

    def serialize(self) -> bytes:
        return self.marker.serialize() + self.content.serialize()

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        s = str(self.content.b,
                encoding='utf_8' if self.marker.type_ == 0x5 else 'ascii')
        if len(s) > 100:
            s = s[:90] + '(etc...)'
        return f"String( {self.marker.pretty_str()}, \"{s}\" )"


@dataclass(kw_only=True)
class UtfStringElement(GameElement):
    """UTF string, ucs2 (utf16le) encoding"""
    content: ByteData

    def serialize(self) -> bytes:
        return self.marker.serialize() + self.content.serialize()

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        s = self.content.b.decode('utf_16_le')
        return f"String( {self.marker.pretty_str()}, \"{s if len(s) < 40 else (s[:40] + '(etc...)')}\" )"


@dataclass(kw_only=True)
class Unknown16Bytes(GameElement):
    """Unknown, but constant size of 16 bytes; maybe UUIDs?"""
    content: bytes

    def serialize(self) -> bytes:
        return self.marker.serialize + content

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"16Bytes( {self.marker.pretty_str()}, {self.content} (or {uuid.UUID(bytes=self.content)}) )"

@dataclass(kw_only=True)
class TimestampElement(GameElement):
    """16 byte element, bytes 9-12 are an epoch timestamp."""
    epoch: int

    def serialize(self) -> bytes:
        return self.marker.serialize + (b'\0' * 8) + _to_bytes(self.epoch) + (b'\0' * 4)

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"Timestamp( {self.marker.pretty_str()}, {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.epoch))} )"


@dataclass(kw_only=True)
class Unknown12Bytes(GameElement):
    """Unknown, but constant size of 12 bytes"""
    content: bytes

    def serialize(self) -> bytes:
        return self.marker.serialize + content

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"16Bytes( {self.marker.pretty_str()}, {self.content} )"


@dataclass(kw_only=True)
class BooleanElement(GameElement):
    """12 bytes to express true-or-false, very efficient"""
    value: int

    def serialize(self) -> bytes:
        return (self.marker.serialize + (b'\0' * 8) +
                _to_bytes(self.value))

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return f"Bool( {self.marker.pretty_str()}, value={self.value} )"


@dataclass(kw_only=True)
class CompressedElement(GameElement):
    """
    Compressed bytes, put inside a bytes string.

    It's usually a DirectDraw Surface, aka an image
    """
    header: bytes
    inflated_size: int
    chunks: list[bytes]

    def _inflate(self, limit=0) -> bytes:
        content: bytes = b''
        z = zlib.decompressobj()
        for chunk in self.chunks:
            content += z.decompress(chunk,
                                    max_length=limit -
                                    len(content) if limit else 0)
            if limit and len(content) >= limit:
                break
        return content

    def serialize(self) -> bytes:
        final_len = len(self.header) + sum(len(chunk) + 4 for chunk in chunks)
        return (self.marker.serialize() +
                ByteData(b=self.header + self.inflated_size.to_bytes(
                    4, "little", signed=False) + b''.join(
                        _to_bytes(len(chunk)) + chunk
                        for chunk in chunks),
                         b_per_element=1).serialize())

    def serialize_uncompressed(self) -> bytes:
        return self.marker.serialize() + ByteData(
            b=self.header + self._inflate(), b_per_element=1).serialize()

    def pretty_str(self) -> str:
        content = self._inflate(limit=60)
        if len(content) >= 60:
            content = content[:50] + b'(etc...)'
        return f"CompressedElement( {self.marker.pretty_str()}, header={self.header}, len={sum(len(chunk) for chunk in self.chunks)}, inflated_size={self.inflated_size}, {content} )"


@dataclass(kw_only=True)
class Array0AElement(GameElement):
    """Array of elements w/ full markers, works like a dict / struct"""
    elements: list[GameElement]

    def serialize(self) -> bytes:
        return b'\0\0\0\x05\0\0\0\0' + len(elements).to_bytes(
            4, "little", signed=False) + b''.join(element.serialize()
                                                  for element in self.elements)

    def serialize_uncompressed(self) -> bytes:
        # TODO: inflate each subelement
        return self.serialize()

    def pretty_str(self) -> str:
        return ("\n".join([f"Array0A ( {self.marker} )"] +
                          [(f"->" + element.pretty_str())
                           for element in self.elements[:10]]) +
                ("" if len(self.elements) <= 10 else
                 f"\n-> (etc... {len(self.elements)} in total)"))


@dataclass(kw_only=True)
class Array0BElement(GameElement):
    """Array of anonymous elements (markers have no name)"""
    header: bytes  # 8
    content: list[GameElement]

    def serialize(self) -> bytes:
        # Make sure to cut off the name of the marker for every element.
        # Hint - this script sets the names to "\0\0\0\0" anyway.
        return self.marker.serialize() + header + b''.join(
            entry.serialize()[4:] for entry in self.content)

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()

    def pretty_str(self) -> str:
        return ("\n".join([
            f"Array0BElement( {self.marker.pretty_str()}, header={self.header} )"
        ] + [entry.pretty_str() for entry in self.content[:5]]) +
                ("" if len(self.content) <= 5 else
                 f"\n(etc... {len(self.content)} in total.)"))



def _parse_marker(input_buffer: BinaryIO, *, name: bytes | None = None) -> Marker | None:
    name = name or input_buffer.read(4)
    if len(name) == 0:
        return None
    return Marker(name=name, type_=_parse_int32(input_buffer))


def _read_byte_data(input_buffer: BinaryIO) -> ByteData | bytes:
    l = int.from_bytes(input_buffer.read(3), "little", signed=False)
    header = input_buffer.read(1)
    if header == b"\x21":
        b_per_element = _parse_int32(input_buffer)
        return ByteData(b=input_buffer.read(l * b_per_element),
                        b_per_element=b_per_element)
    elif l == 0:
        b_per_element_bytes = input_buffer.read(4)
        if (supposed_zeroes:=input_buffer.read(4)) != b'\0'*4:
            RuntimeError(f"Unrecognized string content at {hex(input_buffer.tell()-12)}: {l.to_bytes(2,"little",signed=False) + header + b_per_element_bytes + supposed_zeroes}")
        return l.to_bytes(3, "little", signed=False) + header + b_per_element_bytes 
    else:
        raise RuntimeError(
            f"Unexpected string header at {hex(input_buffer.tell())}: {header}"
        )


def parse_element(marker: Marker,
                  input_buffer: BinaryIO) -> GameElement | None:
    match marker:
        case Marker(type_=0x1):

            if (_buf:=input_buffer.read(8)) != b'\0' * 8:
                print(f"At {hex(input_buffer.tell() - 8)}: Unrecognized bool flags: {_buf}")
                return None
            value = _parse_int32(input_buffer)
            if value > 1:
                print(f"At {hex(input_buffer.tell() - 4)}: Unexpected bool value = {value}")
                return None
            assert value <= 1
            return BooleanElement(marker=marker, value=value)

        case Marker(type_=0x2):
            if (_buf:=input_buffer.read(8)) != b'\0' * 8:
                print(f"At {hex(input_buffer.tell() - 8)}: Unrecognized int flags: {_buf}")
                return None
            return IntElement(marker=marker,
                              value=_parse_int32(input_buffer))
        case Marker(type_=0x3):
            return Unknown12Bytes(marker=marker, content=input_buffer.read(12))

        case Marker(type_=0x4) | Marker(type_=0x5):
            byte_data = _read_byte_data(input_buffer)
            if isinstance(byte_data, bytes):
                # Raw bytes == weird empty string, and returned data is a header
                return UnknownStringElement(marker=marker, header=byte_data)
            assert byte_data.b_per_element == 1
            return StringElement(marker=marker, content=byte_data)

        case Marker(type_=0x6):
            byte_data = _read_byte_data(input_buffer)
            assert byte_data.b_per_element == 2
            return UtfStringElement(marker=marker, content=byte_data)

        case Marker(type_=0xA):
            assert input_buffer.read(8) == b'\0\0\0\x05\0\0\0\0'
            element_count = _parse_int32(input_buffer)
            elements: list[GameElement] = []
            for _ in range(element_count):
                element_marker = _parse_marker(input_buffer)
                element = parse_element(element_marker, input_buffer)
                elements.append(element)
            return Array0AElement(marker=marker, elements=elements)

        case Marker(type_=0xB):
            header = input_buffer.read(8)
            size = _parse_int32(input_buffer)
            entries: list[GameElement] = []
            for _ in range(size):
                entry_type = _parse_int32(input_buffer)
                entries.append(
                    parse_element(Marker(name=b'\0\0\0\0', type_=entry_type),
                                  input_buffer))
            return Array0BElement(marker=marker,
                                  header=header,
                                  content=entries)

        case Marker(type_=0xD):
            return Unknown16Bytes(marker=marker, content=input_buffer.read(16))

        case Marker(type_=0x14): 
            assert input_buffer.read(8) == b'\0\0\0\x80\0\0\0\0'
            timestamp = _parse_int32(input_buffer)
            assert input_buffer.read(4) == b'\0\0\0\0'
            return TimestampElement(marker=marker, epoch=timestamp)
 
        case Marker(type_=0x18):
            byte_data = _read_byte_data(input_buffer)
            with open('debug.bin', 'wb') as debug_file:
                debug_file.write(byte_data.b)
            b = byte_data.b
            header = b[:4]
            inflated_size = int.from_bytes(b[4:8], "little", signed=False)
            chunks: list[bytes] = []
            i = 8
            while i < len(b) and b[i:] != b'\0\0\xFF\xFF':
                if len(b) - i < 4:
                    print(
                        f"Error: at byte no {hex(i)} in a chunk stream length {hex(len(b))}, only {len(b) - i} bytes remain while 4 are needed for chunk length"
                    )
                    exit(1)
                chunk_len = int.from_bytes(b[i:i + 4], "little", signed=False)
                chunks.append(b[i + 4:i + 4 + chunk_len])
                i += 4 + chunk_len
            with open('debug2.bin', 'wb') as debug_file:
                debug_file.write(b''.join(chunks))

            return CompressedElement(marker=marker,
                                     header=header,
                                     inflated_size=inflated_size,
                                     chunks=chunks)

        case anything_else:
            return None


@dataclass(kw_only=True)
class FileSection(ABC):
    """Theory - savefile is divided into sections, each with X elements"""

    def serialize(self) -> bytes:
        ...

    def serialize_uncompressed(self) -> bytes:
        ...


@dataclass(kw_only=True)
class RegularFileSection(FileSection):
    """4 byte name, 4 byte size, content"""
    type_: int
    elements: list[GameElement]

    def serialize(self) -> bytes:
        reported_size = len(self.elements)
        if self.type_ == 1 and reported_size >= 0x40:
            reported_size -= 4 # dunno why
        return (_to_bytes(self.type_) +
                _to_bytes(reported_size) +
                b''.join(element.serialize() for element in self.elements))

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()


@dataclass
class NamelessSection(RegularFileSection):
    def serialize(self) -> bytes:
        return super().serialize()[4:]


@dataclass(kw_only=True)
class EmptyFileSection(FileSection):
    """Labeled as type = 0x10; maybe it's number of file sections left?"""

    def serialize(self) -> bytes:
        return b'\x10\0\0\0'

    def serialize_uncompressed(self) -> bytes:
        return b'\x10\0\0\0'


@dataclass(kw_only=True)
class MultiSection(FileSection):
    """There's a 32-bit number X, then X sections: (i, n, n entries)."""
    subsections: list[tuple[int, list[GameElement]]]

    def serialize(self) -> bytes:
        return (_to_bytes(len(self.elements)) +
                b''.join(
                    _to_bytes(index)
                    + _to_bytes(len(l))
                    + b''.join(elem.serialize() for elem in l)
                    for index, l in self.subsections
                    ))

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()


def parse_n_elements(input_buffer: BinaryIO, n: int) -> list[GameElement]:
    elements: list[GameElement] = []
    for _ in range(n):
        marker = _parse_marker(input_buffer)
        element = parse_element(marker, input_buffer)
        if not element:
            print(f"Error at {hex(input_buffer.tell())}")
            print(f"Fail - unrecognized tag: {marker.pretty_str()}")
        elements.append(element)
    return elements


_MAX_DEFLATED_CHUNK_SIZE = 0x1000000


@dataclass(kw_only=True)
class CompressedSection(FileSection):
    deflated_content: list[bytes]

    def serialize(self) -> bytes:
        b''.join(_to_bytes(len(content)) + content for content in self.deflated_content)

    def serialize_uncompressed(self) -> bytes:
        i = zlib.decompress(b''.join(self.deflated_content))
        return [i[j:j+_MAX_DEFLATED_CHUNK_SIZE] for j in range(0, len(i), _MAX_DEFLATED_CHUNK_SIZE)]


@dataclass(kw_only=True)
class BitmapSection(FileSection):
    """You'd think that it's only 0 and 1 but a-HA! there's also 0x01000001!"""
    type_: int
    size: tuple[int, int]
    bmap: list[int]

    def serialize(self) -> bytes:
        return (_to_bytes(self.type_)
         + size[0].to_bytes(4, "little", signed=False)
         + size[1].to_bytes(4, "little", signed=False)
         + b''.join(_to_bytes(x) for x in self.bmap))

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()


@dataclass(kw_only=True)
class PairsSection(FileSection):
    """Section with 10-byte entries: 4 byte id, 2 byte flags, 4 byte id"""
    entries: list[bytes]

    def serialize(self) -> bytes:
        return (b'\xa5\xa5\0\0'
                + _to_bytes(len(self.entries))
                + b''.join(entries))


@dataclass(kw_only=True)
class AlmostConstantSection(FileSection):
    """
    Section I cannot fathom; seems to be N, N bytes, M, M x 5 bytes.

    On the flipside, this section seems to be almost always the same.
    """
    bytes_: bytes
    flagged_ints: list[bytes]

    def serialize(self) -> bytes:
        return (_to_bytes(len(self.bytes_)) + self.bytes_
                + _to_bytes(len(self.flagged_ints))
                + b''.join(self.flagged_ints)
                + 3 * (b'\x01\0\0\0'))

    def serialize_uncompressed(self) -> bytes:
        return self.serialize()


@dataclass(kw_only=True)
class CustomDataSection(FileSection):
    """
    String-labeled game section.

    In practice - this is only the section labeled "CustomData".
    """
    label: bytes
    elements: list[GameElement]

    def serialize(self) -> bytes:
        return (_to_bytes(len(self.label)) + label
                + _to_bytes(len(self.elements))
                + b''.join(e.serialize() for e in self.elements))


def parse_regular_section(input_buffer: BinaryIO) -> FileSection:
    print(f"At {hex(input_buffer.tell())} ## NEW FILE SECTION")
    type_ = input_buffer.read(4)
    print(f"Section type: {type_}")
    if type_ == b'\x10\0\0\0':
        return EmptyFileSection()

    count = _parse_int32(input_buffer)
    count = count + 4 if (type_[0] == 1 and count > 0x40) else count
    print(f"Expected number of elements: {count}")
    return RegularFileSection(type_=int(type_[0]), elements=parse_n_elements(input_buffer, count))


def parse_nameless_section(input_buffer: BinaryIO) -> NamelessSection:
    print(f"At {hex(input_buffer.tell())} ## NEW NAMELESS SECTION")
    count = _parse_int32(input_buffer)
    count = count + 4 if count > 0x40 else count
    print(f"Expected number of elements: {count}")
    return NamelessSection(type_=-1, elements=parse_n_elements(input_buffer, count))


def parse_multisection(input_buffer: BinaryIO) -> MultiSection:
    print(f"At {hex(input_buffer.tell())} ## NEW MULTISECTION")
    count = _parse_int32(input_buffer)
    print(f"subsection cnt: {count}")
    res: list[tuple[int, list[GameElement]]] = []
    for _ in range(count):
        idx = _parse_int32(input_buffer)
        subcount = _parse_int32(input_buffer)
        print(f"# SUBSECTION idx={idx}, expected {subcount} elements")
        res.append((idx, parse_n_elements(input_buffer, subcount)))
    return MultiSection(subsections=res)


def parse_compressed(input_buffer: BinaryIO) -> CompressedSection:
    print(f"At {hex(input_buffer.tell())} ## NEW COMPRESSED SECTION")
    data: list[bytes] = []
    while True:
        chunk_size = _parse_int32(input_buffer)
        # print(f"CHUNK at {hex(input_buffer.tell())} size={chunk_size}")
        data.append(input_buffer.read(chunk_size))
        if chunk_size < 0x10000:
            print(f"Read {len(data)} chunks for a total of {hex(sum(len(d) for d in data))} bytes")
            return CompressedSection(deflated_content=data)


def parse_bmap(input_buffer: BinaryIO) -> BitmapSection:
    print(f"At {hex(input_buffer.tell())} ## NEW BITMAP SECTION")
    type_ = _parse_int32(input_buffer)
    size = (_parse_int32(input_buffer),
            _parse_int32(input_buffer))
    print(f"Section type={type_}, size={size}, expected {hex(size[0]*size[1]*4)} bytes")

    data: list[int] = [
            _parse_int32(input_buffer)
            for _ in range(size[0] * size[1])
    ]
    return BitmapSection(type_=type_, size=size, bmap=data)


def parse_pairs_section(input_buffer: BinaryIO) -> PairsSection:
    print(f"At {hex(input_buffer.tell())} ## NEW PAIRS SECTION")
    assert input_buffer.read(4) == b'\xa5\xa5\0\0'
    count = _parse_int32(input_buffer)
    print(f"No pairs: {count}")
    return PairsSection(entries=[input_buffer.read(10) for _ in range(count)])


def parse_jack_shit(input_buffer: BinaryIO) -> list[GameElement | bytes]:
    assert input_buffer.read(4) == b'CIV6'
    result: list[GameElement | bytes] = []
    elements_since = 0
    while (tag_bytes:=input_buffer.read(4)) is not None:
        skip_target_pos = input_buffer.tell()
        marker = _parse_marker(input_buffer, name=tag_bytes)
        if (element:=parse_element(marker, input_buffer)) is None:
            result.append(tag_bytes)
            if elements_since:
                print("+", elements_since)
            print(hex(skip_target_pos-4), tag_bytes)
            elements_since = 0
            if tag_bytes == b'\0\0\x01\0':
                return result
            input_buffer.seek(skip_target_pos)
        else:
            result.append(element)
            #print("+1")
            elements_since += 1
            #print(hex(skip_target_pos-4), element.pretty_str())
    return result


def parse_weird_constant_data(input_buffer: BinaryIO) -> AlmostConstantSection:
    print(f"At {hex(input_buffer.tell())} ## NEW Weird constant data SECTION")
    len_bytes = _parse_int32(input_buffer)
    bytes_ = input_buffer.read(len_bytes)
    len_tuples = _parse_int32(input_buffer)
    tuples = [input_buffer.read(5) for _ in range(len_tuples)]
    assert input_buffer.read(12) == 3 * b'\x01\0\0\0'
    return AlmostConstantSection(bytes_=bytes, flagged_ints=tuples)


def parse_custom_data(input_buffer: BinaryIO) -> CustomDataSection:
    print(f"At {hex(input_buffer.tell())} ## NEW CUSTOMDATA SECTION")
    len_label = _parse_int32(input_buffer)
    label = input_buffer.read(len_label)
    print(label)
    count = _parse_int32(input_buffer)
    print(f"Expected number of elements: {count}")
    return CustomDataSection(label=label, elements=parse_n_elements(input_buffer, count))


def parse_civ6save(input_buffer: BinaryIO) -> list[FileSection]:
    # Stage 0: magic bytes
    assert input_buffer.read(4) == b'CIV6'

    # Stage 1: File sections of form "some int, num of entries, entries"
    result: list[FileSection] = []
    while True:
        section = parse_regular_section(input_buffer)
        result.append(section)
        if isinstance(section, RegularFileSection) and not section.elements:
            break

    # Stage 2: 1x Multisection
    result.append(parse_multisection(input_buffer))

    # Stage 3: 1x Nameless section
    result.append(parse_nameless_section(input_buffer))

    # Stage 4: Compressed sectionn
    result.append(parse_compressed(input_buffer))

    # Stage 5: Bitmap
    result.append(parse_bmap(input_buffer))

    # Stage 6: Weird pairs
    result.append(parse_pairs_section(input_buffer))

    # Stage 7: Completely not understood section, but constant between files
    result.append(parse_weird_constant_data(input_buffer))

    # Stage 8: CustomData section
    result.append(parse_custom_data(input_buffer))

    after_parsing_at = input_buffer.tell()
    input_buffer.seek(0, SEEK_END)
    file_end_at = input_buffer.tell()
    if after_parsing_at != file_end_at:
        raise RuntimeError(f"Parsed all expected sections but finished before end of file (at {hex(after_parsing_at)} instead of {hex(file_end_at)})")

    return result


def raw_byte_analysis(l: list[GameElement | bytes]) -> list[int | bytes]:
    res: list[int | bytes] = []
    since_last_elem = 0
    for elem in l:
        if isinstance(elem, bytes):
            if since_last_elem:
                res.append(since_last_elem)
            since_last_elem = 0
            res.append(elem)
        else:
            since_last_elem += 1
    return res


if __name__ == "__main__":
    # file_name = 'AutoSave_0108.Civ6Save'
    # file_name = 'PACHACUTI 1 4000 BC.Civ6Save'
    for i in range(1, 109):
        with open(f'AutoSave_{i:04}.Civ6Save', 'rb') as savefile:
            parse_civ6save(savefile)
    
