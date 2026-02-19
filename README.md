# Repackaging .Civ6Save files

This repo was meant to provide a script that can repackage AutoSave files.

It fails to do so.

### Background

Tournament play sometimes uses all AutoSaves from a game for further insight,
whether it's play-by-play strategy analysis or cheat investigations. They can
be then fed to [Civ 6 Replay tool](https://sourceforge.net/projects/civ-vi-replay/).

A 100-ish turn game takes up ~350 MB in storage, 240 MB when put into .rar.
In my eyes this is bad - there should be a more efficient way of making such 
archive.

I assumed that the bad compression rate comes from the saves already containing
compressed data. My hypothesis was that decompressing each file's contents and
_then_ compressing it as one big archive would be more efficient.

Well, that assumption was wrong so far - using Zlib or Gzip2 on concatenated raw
data instead of compressed bytes got me only down to ~200MB. Far cry from what
I wanted to achieve.

But I uploaded my work regardless. Someone else may find this repo and  use the 
it for a quicker start into reverse-engineering the .Civ6Save format.

# Parsing .Civ6Save files

This analysis covers **every byte** of the .Civ6Save file, except for the
meatiest bit - the entire game state, with the world map and other whatnots.
I fell short on working this part out.

Otherwise, the rest of the file structure was left with "no bytes skipped".
Each piece of the file structure is either explained or explicitly marked as not
understood yet. Unlike prior work, there's never a point where "we skip bytes 
until hopefully encountering familiar structure again" - if we skip any bytes,
we know how many and (roughly) why.

## Before you dive in, I insist you learn this first:

Most pieces of data are written with **4-byte words**.\
You'll see a lot of blocks where 4-byte alignment is apparent. Take this example:

```
00043a80  ff ff ff ff 5f 5e cd e8  05 00 00 00 00 00 00 00  |...._^..........|
00043a90  00 00 00 00 00 00 00 00  1a 35 43 f0 05 00 00 00  |.........5C.....|
00043aa0  00 00 00 00 00 00 00 00  00 00 00 00 dc f1 5b f8  |..............[.|
00043ab0  02 00 00 00 00 00 00 00  00 00 00 00 af 24 46 f5  |.............$F.|
00043ac0  1f e3 57 0b 0a 00 00 00  00 00 00 05 00 00 00 00  |..W.............|
00043ad0  05 00 00 00 2f 52 96 1a  02 00 00 00 00 00 00 00  |..../R..........|
00043ae0  00 00 00 00 3e 00 00 00  a2 02 2a 54 0a 00 00 00  |....>.....*T....|
00043af0  00 00 00 05 00 00 00 00  00 00 00 00 b1 04 bd a4  |................|
00043b00  01 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  |................|
00043b10  95 b9 42 ce 02 00 00 00  00 00 00 00 00 00 00 00  |..B.............|
```
This example highlights two most frequent data elements:
* 32-bit integers, **always little-endian** (e.g. `05 00 00 00`),
* 32-bit "field identifiers" (e.g. `5f 5e cd e8`). Based on some fiddling with
Civ6 decompilation, I assume these are hashes of Lua field names found in the
game state.

Not the entire file is 4-byte aligned, because there's plenty of variable-sized
strings - these are only byte-aligned and throw off the general 4-byte alignment.

## Sections

The file seems to be divided into distinct sections. Some share the tag
structure described in the next section, some have a different, unique
structure.

Here's the rundown of the sections I identified, in the order they appear
(there's no padding / gap / extra bytes between them):

| No. | Section                         | Description                                                                                                                                                                                                                                                                                               |
|:----|---------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0   | Magic bytes                     | Always 4-bytes, always equal to `CIV6`                                                                                                                                                                                                                                                                    |
| 1   | "Normal" tagged data            | * 1 word (probably identifying section type / id) <br> * 1 word as 32-bit number N: how many tags are in this section <br> * N tags follow                                                                                                                                                                |
| 1\* | ...                             | There are multiple sections like section 1, one after another. <br> Final one has N = 0 elements                                                                                                                                                                                                          |
| 2   | A "set" of tagged data sections | * 1 word as 32-bit number M - number of sub-sections <br> * M sub-sections follow (see section 2.1.)                                                                                                                                                                                                      |
| 2.1 | Subsection of the "set"         | * 1 word - probably ID of the subsection <br> * 1 word as 32-bit number N: how many tags are in this section <br> * N tags follow                                                                                                                                                                         |
| 3   | Tagged data ("id-less")         | * 1 word as 32-bit number N: how many tags are in this section <br> * N tags follow                                                                                                                                                                                                                       |
| 4   | Compressed section              | Binary data compressed with Zlib and split into chunks; contains most game data <br> The following pattern repeats: <br> * 1 word as 32-bit integer N - size of the chunk in bytes, always <= 65536 (0x10000) <br> * N bytes - chunk content <br> <br> Section ends with a chunk smaller than 65536 bytes |
| 5   | "Bitmap"                        | * 1 word - probably ID of the section <br> * 1 word as 32-bit number N <br> * 1 word as 32-bit number M <br> * N\*M words, each a 32-bit integer, each value equal to one of the following: 0x0, 0x1 or 0x1000001                                                                                         |
| 6   | Unidentified section #1         | * 1 word - probably ID of the section, always `a5 a5 00 00` <br> * 1 word as 32-bit number N <br> * N entries, 10 bytes each <br> _Theory: entry structure is: 1-word ID, 2 one-byte flags (each byte is equal to either 0 or 1), then another 1-word ID_                                                 |
| 7   | Unidentified section #2         | * 1 word as 32-bit number N <br> * N bytes <br> * 1 word as 32-bit number M <br> * M entries, 5 bytes each (5th byte seems to always be 0) <br> * 12 bytes, always `01 00 00 00 01 00 00 00 01 00 00 00`                                                                                                  |
| 8   | Custom data                     | * 1 word as 32-bit number N (usually 0xa) <br> * N bytes w/ ASCII name of the section (usually 'CustomData') <br> * 1 word as 32-bit number M <br> * M tags follow                                                                                                                                        |

## Tagged data

Sections 1, 2, 3 and 8 follow a consistent structure: after the header, there's
N entries of known structure. **The only exception is in section 1 - if a
section starts with word `10 00 00 00` as section ID - the section immediately 
ends and next section starts.**

Each of the tagged entries has a metastructure of:

| bytes   | content                                                                                             |
| ---     |-----------------------------------------------------------------------------------------------------|
| 0x0-0x3 | identifier, probably hash of the field available in Lua (e.g. `99 b0 d9 05` stands for `GameSpeed`) |
| 0x4-0x7 | data type, as a 32-bit integer                                                                      |
| 0x8-??  | data content                                                                                        |

Depending on the number in the "data type" part of the entry, data content 
length and structure varies.

Here's the list of all possible data types, along with their data content layout:

| data type (number) | data type (unofficial) name      | data content memory layout                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---: |----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0x01 | Boolean                          | 3 words total: <br> * 2 words - both are always `00 00 00 00` <br> * 1 word - either `00 00 00 00` or `01 00 00 00`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| 0x02 | Integer                          | 3 words total: <br> * 2 words - both are always `00 00 00 00` <br> * 1 word - a 32-bit integer (_the_ content)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| 0x03 | "Unknown" 12 bytes (RGBA color)? | 3 words total - unknown meaning <br> _Note - I found that for entries I actually managed to identify, the last word is an RGBA color <br> (see entries with ID `15 87 98 85` ("HostForegroundColorValue") and `81 6f 54 7c` ("HostBackgroundColorValue")_                                                                                                                                                                                                                                                                                                                                                                      |
| 0x04 | ASCII string                     | 2 words + ? bytes total: <br> * 3 bytes - 24-bit integer N <br> * 1 byte - always 0x21 <br> * 1 word as 32-bit integer M - no. bytes per character; always = 1 <br> * N\*M = N\*1 = N bytes <br> <br> **IMPORTANT NOTE:** Empty strings are sometimes represented as a special 8-byte sequence, equal to `00 00 00 20 00 00 00 00`                                                                                                                                                                                                                                                                                             |
| 0x05 | Utf-8 string                     | Same as above                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 0x06 | Utf-16 string                    | Same as above, except M is always equal to 2; <br> This makes the string content N\*2 bytes long                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 0x0A | Object / Map                     | _An entry that contains N sub-entries, each with its own tag_ <br> 3-words + ? bytes total: <br> * 2-word header, always `00 00 00 05 00 00 00 00` <br> * 1 word as 32-bit integer N <br> * N full entries, i.e. each with its own ID, data type and data content                                                                                                                                                                                                                                                                                                                                                              |
| 0x0B | Array                            | _An entry that contains N sub-entries; sub-entries lack IDs of their own_ <br> 3 words + ? bytes total: <br> * 2-word header, always `00 00 00 11 00 00 00 00` <br> * 1 word as 32-bit integer N <br> * N entries, each has 1-word data type followed by data content (compared to a normal tagged entry it's missing the first word - the ID)                                                                                                                                                                                                                                                                                 |
| 0x0D | Unknown 16 bytes                 | 16 bytes - unknown meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 0x14 | Timestamp                        | 4 words total: <br> * 2 words - always `00 00 00 80 00 00 00 00` <br> * 1 word as 32-bit integer - a UNIX timestamp (in seconds) <br> * 1 word, always `00 00 00 00`                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 0x15 | Unknown "8 byte content"         | 16 bytes total (sike!): <br> * 2 words, always `00 00 00 80 00 00 00 00` <br> * 8 bytes - meaning unknown                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 0x18 | Compressed data (a picture?)     | _Data layout same as for 0x04 (ASCII string)_ <br> <br> Contained string can be interpreted as binary data of following structure: <br> * 4 bytes - unknown menaing <br> * 4 bytes - 32-bit integer, expected size of inflated (e.g. decompressed) content <br> _Until the string end, the following pattern repeats:_ <br> * 4 bytes - 32-bit integer N - length of the chunk <br> * N bytes - chunk content <br> <br> Concatenated chunks will form a Zlib-compressed file contents. <br> _I found that more often than not, the content of that archive is a DDS file (i.e. "DirectDraw Surface", a BMP-like image format)_ |

## WHERE ACTUAL GAMEPLAY DATA?!

The tag system described above will probably get you most of the game _meta_ data,
such as: the name of the save file in "Load Game" menu, current turn, list of Civs 
in the game, game speed, game map, thumbnail pictures used in "Load Game" menu etc.

If you want gameplay data such as the world map, all cities, all units, techs
researched etc, look into what I marked as "Section 4. Compressed Section".\
I have _no idea_ how that section is built. I recommend looking into
[Civ6Save-analysis](https://github.com/lucienmaloney/civ6save-editing/blob/master/Civ6Save-analysis/bin-structure.md)
repo for a headstart into interpreting the content on your own.

## Credits

* https://github.com/pydt/civ6-save-parser - prior work on .Civ6Save as
tag-based file structure, made this project possible

* https://github.com/lucienmaloney/civ6save-editing - prior work on "the 
compressed" section of the file. Didn't use it yet, but describes the way map
data is stored in the internal DEFLATEd archive.
