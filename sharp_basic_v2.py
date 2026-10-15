#!/usr/bin/env python3
"""
Sharp pocket computer BASIC tokenizer / detokenizer (PC-125x, PC-1403 family, PC-1500, PC-1600).

Usage:
    python3 sharp_basic_v2.py det [--model M] input.bin [output.bas]
    python3 sharp_basic_v2.py tok --model M input.bas output.bin

--model is the only option.  For det it is optional: the model family is detected from the
file (models of one family share a token table).  For tok it defaults to 1403.  det omits blank lines and prints to the screen when no output
file is given.  tok writes no header; the end marker is the usual one for the model.

PC-125x (--model 1251 etc., also 1245-1255, 1150, 1140, 1210-1212) use single-byte
tokens in their own character code (letters 51..6A, digits 40..49, space 11) and
store a line as  E0+hundreds, BCD tens/units, body, 00  (line numbers 1-999, no
length byte).  Images carry no header; a tape/Transfile stream (ID 20, 8 data
bytes + checksum per block) can be read with --tape.  Characters without a known
code are shown as <XX> (e.g. <4B> = the exponent E of 1E-8), tokens inside strings
too.  Verified against 19 real PC-1251 tape recordings (all 19 programs decode and
re-tokenize byte for byte).  The PC-1210/1211/1212 use the same layout with a
reduced keyword set.  These models have one code per letter, so lower case is
converted to upper case when tokenizing (also inside strings) and is lost.

PC-1280 / 1360 / 1470 / 1475 (--model 1360 etc.) use the PC-1403 line layout but
2-byte tokens FE xx (PRINT = FE 60, REM = FE 59), from the Pocket Tools table.
Constant jump targets (GOTO 100, THEN 60, ON..GOTO 10,20) are stored as 1F hi lo.

PC-E500 / E500S / E550 / E650 / U6000 / PC-1480U / 1490U (--model E500 ...) and
PC-E200 / E220 / G801 ... G850 / G850V (--model E220, G815, G850, G850V) use the same
FE xx tokens plus the special bytes 1D (BCD number), 1E (skip), 1C (long jump) and, on
the E500, 00 lo hi (absolute jump written by the pocket).  det decodes all of them.
tok is experimental here, as in Pocket Tools: numbers stay ASCII, so on a PC-E500 enter
TEXT and then BASIC after loading an image.  Spaces are kept, text after ' or REM is raw.

det is tolerant: it keeps going after damaged lines (wrong length byte, missing end of
line, line numbers out of order, unknown bytes shown as <XX>) so they can be fixed by hand.

PC-1500 / PC-1600 (--model 1500 or 1600) use 2-byte tokens (PRINT = F0 97) and the
same line layout; the image ends with 00 00 (optional), FF 00 00 separates program
segments (shown as a "#SEGMENT" line), the PC-1600 stores constant GOTO/GOSUB/THEN/
RESUME/RUN/RESTORE targets as 1F hi lo 00, dotted abbreviations (P. = PRINT) are
expanded on the PC-1500, and text after REM or ' is raw.  Headers (CE-158 / PC-1600
serial headers) are skipped automatically when reading; use --offset to force a position.
Tested byte-for-byte against real PC-1500 and PC-1600 files (SharpDataExchange fixtures).

Image layout (CSAVE / IMG files)
--------------------------------
    <header>                      optional, length detected automatically when reading
    repeated for every line:
        hi lo                     line number, big endian (00 0A = line 10)
        len                       number of bytes that follow (body + 0D)
        body                      tokenized line
        0D                        end of line
    FF                            end-of-program marker (optional when reading)

Token namespaces
----------------
* Bytes 80..EE are single-byte tokens (TOKENS).
* EF + byte selects a second namespace (EXT_TOKENS): the alternate [bracketed]
  keyword names of the table (file-system commands of the PC-1475 family).
* Bytes inside "string literals" are never interpreted as tokens.
* Unknown bytes are written as <XX> when detokenizing, and <XX> is turned back
  into that byte when tokenizing, so round trips lose nothing.

Tokenizer rules (modelled on how the machine stores a line)
-----------------------------------------------------------
* Outside strings, blanks are dropped, letters are upper-cased and keywords are matched
  case-insensitively, longest match first (so PRINT beats PRE.., MEM# beats MEM).
* "&" is followed by hex digits that are copied as they are (&F4DB is not
  scanned for keywords).
* Text after REM is stored raw (use --rem-tokenize to tokenize it anyway);
  one blank right after REM is dropped, because the detokenizer adds one.
* Abbreviated keywords with a trailing dot (P. for PRINT) are NOT expanded.
* Keywords hidden inside a variable name are tokenized, as on the real
  machine (e.g. a variable called "TOP" would become TO + P).

Sources: Wikipedia "Sharp pocket computer character sets" (PC-14xx table,
which cites the PC-1403 and PC-1475 operation manuals) and the Pocket Tools 2.1
manual (token groups per model).  Only the PC-1403 has been tested on real
files; every other model reuses that table (see MODEL_GROUPS).
"""

import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Single-byte tokens
# --------------------------------------------------------------------------
TOKENS = {
    # 8x
    0x80: "MDF", 0x81: "REC", 0x82: "POL", 0x83: "ROT", 0x84: "DECI",
    0x85: "HEX", 0x86: "TEN", 0x87: "RCP", 0x88: "SQU", 0x89: "CUR",
    0x8A: "HSN", 0x8B: "HCS", 0x8C: "HTN", 0x8D: "AHS", 0x8E: "AHC",
    0x8F: "AHT",
    # 9x
    0x90: "FACT", 0x91: "LN", 0x92: "LOG", 0x93: "EXP", 0x94: "SQR",
    0x95: "SIN", 0x96: "COS", 0x97: "TAN", 0x98: "INT", 0x99: "ABS",
    0x9A: "SGN", 0x9B: "DEG", 0x9C: "DMS", 0x9D: "ASN", 0x9E: "ACS",
    0x9F: "ATN",
    # Ax
    0xA0: "RND", 0xA1: "AND", 0xA2: "OR", 0xA3: "NOT", 0xA4: "ASC",
    0xA5: "VAL", 0xA6: "LEN", 0xA7: "PEEK", 0xA8: "CHR$", 0xA9: "STR$",
    0xAA: "MID$", 0xAB: "LEFT$", 0xAC: "RIGHT$", 0xAD: "INKEY$", 0xAE: "PI",
    0xAF: "MEM",
    # Bx
    0xB0: "RUN", 0xB1: "NEW", 0xB2: "CONT", 0xB3: "PASS", 0xB4: "LIST",
    0xB5: "LLIST", 0xB6: "CSAVE", 0xB7: "CLOAD", 0xB8: "MERGE",
    0xB9: "EQU#",      # table cell "EQU#/ ARMT"
    0xBA: "MEM#",      # table cell "MEM#/ COMP"
    0xBB: "OPEN", 0xBC: "CLOSE", 0xBD: "SAVE", 0xBE: "LOAD",
    0xBF: "CONSOLE",   # table cell "CONSOLE/ DAYSII"
    # Cx
    0xC0: "RANDOM", 0xC1: "DEGREE", 0xC2: "RADIAN", 0xC3: "GRAD",
    0xC4: "BEEP", 0xC5: "WAIT", 0xC6: "GOTO", 0xC7: "TRON", 0xC8: "TROFF",
    0xC9: "CLEAR", 0xCA: "USING", 0xCB: "DIM", 0xCC: "CALL", 0xCD: "POKE",
    0xCE: "CLS",       # table cell "CLS/ BGNON"
    0xCF: "CURSOR",    # table cell "CURSOR/ BGNOFF"
    # Dx
    0xD0: "TO", 0xD1: "STEP", 0xD2: "THEN", 0xD3: "ON", 0xD4: "IF",
    0xD5: "FOR", 0xD6: "LET", 0xD7: "REM", 0xD8: "END", 0xD9: "NEXT",
    0xDA: "STOP", 0xDB: "READ", 0xDC: "DATA", 0xDD: "PAUSE", 0xDE: "PRINT",
    0xDF: "INPUT",
    # Ex
    0xE0: "GOSUB", 0xE1: "AREAD", 0xE2: "LPRINT", 0xE3: "RETURN",
    0xE4: "RESTORE", 0xE5: "CHAIN",   # table cell "CHAIN/ ERASE"
    0xE6: "GCURSOR", 0xE7: "GPRINT", 0xE8: "LINE", 0xE9: "POINT",
    0xEA: "PSET", 0xEB: "PRESET", 0xEC: "BASIC", 0xED: "TEXT",
    0xEE: "OPEN$",
    # 0xEF is the prefix byte for EXT_TOKENS
}

# Tokens that the shared PC-14xx table lists but that may belong to a sibling
# model (PC-1403H / PC-1475) rather than a plain PC-1403.  They are still
# decoded (better than <XX>), but listed in the summary when they occur.
FAMILY_ONLY = {
    0xB9, 0xBA, 0xBF,                           # EQU#, MEM#, CONSOLE
    0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB,         # GCURSOR GPRINT LINE POINT PSET PRESET
    0xEC, 0xED, 0xEE,                           # BASIC TEXT OPEN$
    0x80, 0x81, 0x82, 0x83,                     # MDF REC POL ROT (see also EXT)
}

# --------------------------------------------------------------------------
# EF-prefixed tokens (the [bracketed] alternate names of the table)
# --------------------------------------------------------------------------
EXT_TOKENS = {
    0x80: "EOF",    0x81: "DSKF",   0x82: "LOF",    0x83: "LOC",
    0xA1: "XOR",    0xA8: "RENUM",  0xA9: "DELETE",
    0xB0: "FILES",  0xB1: "LFILES", 0xB2: "INIT",   0xB3: "KILL",
    0xB4: "NAME",   0xB5: "SET",    0xB6: "COPY",
    0xE0: "OUTPUT", 0xE1: "APPEND", 0xE2: "AS",
}

# --------------------------------------------------------------------------
# Models -> token-table groups (grouping taken from the Pocket Tools 2.1
# manual, section 6.4.1, "Pc=Number")
# --------------------------------------------------------------------------
#   group   models                                           table used here
#   1211    1210, 1211, 1212                                 OLD table (layout unverified)
#   OLD     1140, 1150, 1245-1255 (+ 1210-1212)             OLD_TOKENS (tape-verified)
#   NEW     1100, 1260-1262, 1350, 1401/02, 1430/31, 1450    TOKENS (PC-1403 table, UNVERIFIED subset)
#   NEW3    1403, 1425, 1440, 1445, 1460  (incl. NEW tokens) TOKENS + EXT_TOKENS
#   EXT     1280, 1360, 1470, 1475                           TOKENS + EXT_TOKENS (UNVERIFIED)
# NEW3 is a superset of NEW, but no source I found says which codes belong to
# NEW only, so the NEW group reuses the full table; keywords that only exist
# on NEW3 models would be mis-decoded (a program for a NEW-group machine would
# not contain them, so this mostly matters for damaged files).
MODEL_GROUPS = {}
for _m in (1403, 1425, 1440, 1445, 1460):
    MODEL_GROUPS[_m] = "NEW3"
for _m in (1100, 1260, 1261, 1262, 1350, 1401, 1402, 1430, 1431, 1450):
    MODEL_GROUPS[_m] = "NEW"
for _m in (1280, 1360, 1470, 1475):
    MODEL_GROUPS[_m] = "EXT"
for _m in (1500,):
    MODEL_GROUPS[_m] = "PC1500"
for _m in (1600,):
    MODEL_GROUPS[_m] = "PC1600"
for _m in (500, 550, 650, 6000, 1480, 1490):
    MODEL_GROUPS[_m] = "E"                    # PC-E500 / E500S / E550 / E650 / U6000 / 1480U / 1490U
for _m in (200, 220, 801, 802, 803, 805, 811, 813, 815, 820, 830, 850, 852):
    MODEL_GROUPS[_m] = "G"                    # PC-E200, E220, G801 ... G850, G850V (852)
for _m in (1210, 1211, 1212):
    MODEL_GROUPS[_m] = "P1211"
for _m in (1140, 1150) + tuple(range(1245, 1256)):
    MODEL_GROUPS[_m] = "OLD"

# group -> (EF names when detokenizing, EF names when tokenizing, verified?)
# Tokenizing with EF names is off for NEW3 so that short names such as AS or
# SET are not picked out of ordinary variable names on a plain PC-1403.
GROUP_PROFILE = {
    "NEW3": (True,  False, True),    # table source: PC-1403 / PC-1475 manuals
    "NEW":  (False, False, False),   # base table reused, EF prefix not expected
    "EXT":  (True,  True,  True),    # FE xx tokens (EXT2_* tables)
    "E":    (True,  True,  True),    # PC-E500 family, FE xx tokens
    "G":    (True,  True,  True),    # PC-E200/E220/G800 series, FE xx tokens
    "OLD":  (False, False, True),    # PC-125x tokens (OLD_TOKENS)
    "P1211": (False, False, True),   # PC-1210/11/12: reduced subset of OLD_TOKENS
    "PC1500": (False, False, True),  # separate 2-byte token set (Registry)
    "PC1600": (False, False, True),
}

# Other prefix bytes from the table (not decoded, only named in messages):
#   FE = prefix of the CE-126P printer character set
#   FF = "Japan prefix" (undocumented Japanese character mode)
# Note: FF at the *start of a line record* is the end-of-program marker.

EOP = 0xFF

# --------------------------------------------------------------------------
# PC-1500 / PC-1600 keyword tables (2-byte tokens)
# --------------------------------------------------------------------------
# These machines (SC7852 CPU) store every keyword as a 2-byte code, e.g.
# PRINT = F0 97, and use the same line layout as the PC-1403 images
# (hi lo len body 0D).  The tables below are in lookup order ("later entry
# wins" on a name or code collision): PC-1500 + CE-150 plotter + CE-158
# interface for the PC-1500 set, CE-150 + CE-158 + PC-1600 for the PC-1600 set.
#
# Data source: SharpDataExchange, src/keywords.rs (generated there from
# SharpBasicShared), Copyright 2026 Martin Erzberger, Polyform Noncommercial
# License 1.0.0 (https://polyformproject.org/licenses/noncommercial/1.0.0).
# That license allows noncommercial use only; keep this notice if you
# redistribute the table.  The PC-1500 part was cross-checked against the
# Pocket Tools 2.1 file KEYWORDS/01-PC-1500.KEY.
# Each entry: NAME SHORTEST-ABBREVIATION CODE
_PC1500_DATA = """
    ABS AB F170; ACS AC F174; ASC ASC F160; ASN AS F173
    ATN AT F175; CHR$ CH F163; COS COS F17E; DEG DEG F165
    DMS DM F166; ERL ERL F053; ERN ERN F052; EXP EX F178
    INKEY$ INK F15C; INT INT F171; LEFT$ LEF F17A; LEN LEN F164
    LN LN F176; LOG LO F177; MEM M F158; MID$ MI F17B
    PEEK PEEK F16F; PEEK# PE F16E; PI PI F15D; POINT POI F168
    RIGHT$ RI F172; RND RN F17C; SGN SG F179; SIN SI F17D
    SPACE$ SPACE$ F061; SQR SQ F16B; STATUS STA F167; STR$ STR F161
    TAN TA F17F; TIME TI F15B; VAL V F162; AREAD A F180
    ARUN ARU F181; BEEP B F182; BREAK BREAK F0B3; CALL CA F18A
    CHAIN CHA F0B2; CLEAR CL F187; CLOAD CLO F089; CLS CLS F088
    CONSOLE CONSOLE F0B1; CONT C F183; CSAVE CS F095; CURSOR CU F084
    DATA DA F18D; DEGREE DE F18C; DIM D F18B; END E F18E
    ERROR ER F1B4; FEED FEED F0B0; FOR F F1A5; GOSUB GOS F194
    GOTO G F192; GRAD GR F186; IF IF F196; INPUT I F091
    LET LE F198; LF LF F0B6; LIST L F090; LOCK LOC F1B5
    MERGE MER F08F; NEW NEW F19B; NEXT N F19A; OFF OFF F19E
    ON O F19C; OPN OPN F19D; PAUSE PA F1A2; POKE POKE F1A1
    POKE# PO F1A0; PRINT P F097; RADIAN RAD F1AA; RANDOM RA F1A8
    READ REA F1A6; REM REM F1AB; RESTORE RES F1A7; RETURN RE F199
    RUN R F1A4; STOP S F1AC; TAB TAB F0BB; TROFF TROF F1B0
    TRON TR F1AF; UNLOCK UN F1B6; USING U F085; WAIT W F1B3
    ZONE ZONE F0B4; AND AN F150; NOT NO F16D; OR OR F151
    STEP STE F1AD; THEN T F1AE; TO TO F1B1; COLOR COL F0B5
    CSIZE CSI E680; GCURSOR GCU F093; GLCURSOR GL E682; GPRINT GP F09F
    GRAPH GRAP E681; LCURSOR LCU E683; LINE LIN F0B7; LLIST LL F0B8
    LPRINT LP F0B9; RLINE RL F0BA; ROTATE RO E685; SORGN SO E684
    TEXT TEX E686; COM$ COM$ E858; DEV$ DEV$ E857; INSTAT INSTAT E859
    OUTSTAT OUTSTAT E880; RINKEY$ RINKEY$ E85A; DTE DTE E884; PROTOCOL PROTOCOL E881
    RMT RM E7A9; SETCOM SETCOM E882; SETDEV SETDEV E886; TERMINAL TERMINAL E883
    TEST TE F0BC; TRANSMIT TRANSMIT E885
"""

_PC1600_DATA = """
    COLOR COL F0B5; CSIZE CSI E680; GCURSOR GCU F093; GLCURSOR GL E682
    GPRINT GP F09F; GRAPH GRAP E681; LCURSOR LCU E683; LINE LIN F0B7
    LLIST LL F0B8; LPRINT LP F0B9; RLINE RL F0BA; ROTATE RO E685
    SORGN SO E684; TEXT TEX E686; COM$ COM$ E858; DEV$ DEV$ E857
    INSTAT INSTAT E859; OUTSTAT OUTSTAT E880; RINKEY$ RINKEY$ E85A; DTE DTE E884
    PROTOCOL PROTOCOL E881; RMT RM E7A9; SETCOM SETCOM E882; SETDEV SETDEV E886
    TERMINAL TERMINAL E883; TEST TE F0BC; TRANSMIT TRANSMIT E885; ABS ABS F170
    ACS ACS F174; AIN AIN F25A; ALARM$ ALARM$ F25C; ASC ASC F160
    ASN ASN F173; ATN ATN F175; CHR$ CHR$ F163; COM$ COM$ E858
    COS COS F17E; DATE$ DATE$ F257; DEG DEG F165; DEV$ DEV$ E857
    DMS DMS F166; DSKF DSKF F274; EOF EOF F271; ERL ERL F053
    ERN ERN F052; EXP EXP F178; HEX$ HEX$ F265; INKEY$ INKEY$ F15C
    INP INP F266; INSTAT INSTAT E859; INSTR INSTR F267; INT INT F171
    KBUFF$ KBUFF$ F284; KEYSTAT KEYSTAT F286; LEFT$ LEFT$ F17A; LEN LEN F164
    LN LN F176; LOC LOC F272; LOG LOG F177; LOF LOF F273
    MEM MEM F158; MID$ MID$ F17B; OUTSTAT OUTSTAT E880; PEEK PEEK F26D
    PEEK# PEEK# F26E; PI PI F15D; POINT POINT F168; RCVSTAT RCVSTAT F2A4
    RIGHT$ RIGHT$ F172; RINKEY$ RINKEY$ E85A; RND RND F17C; RXD$ RXD$ F256
    SGN SGN F179; SIN SIN F17D; SNDSTAT SNDSTAT F2A2; SPACE$ SPACE$ F061
    SQR SQR F16B; STATUS STATUS F167; STR$ STR$ F161; TAN TAN F17F
    TIME TIME F15B; TIME$ TIME$ F258; VAL VAL F162; WAKE$ WAKE$ F261
    XPEEK XPEEK F16F; XPEEK# XPEEK# F16E; ADIN ADIN F280; AOFF AOFF F2BC
    AREAD AREAD F180; ARUN ARUN F181; AUTO AUTO F2B6; BEEP BEEP F182
    BLOAD BLOAD F290; BREAK BREAK F0B3; BSAVE BSAVE F291; CALL CALL F282
    CHAIN CHAIN F0B2; CLEAR CLEAR F187; CLOAD CLOAD F089; CLOSE CLOSE F292
    CLS CLS F088; COLOR COLOR F0B5; COM COM F2A3; CONSOLE CONSOLE F0B1
    CONT CONT F183; COPY COPY F293; CSAVE CSAVE F095; CSIZE CSIZE E680
    CURSOR CURSOR F084; DATA DATA F18D; DEGREE DEGREE F18C; DELETE DELETE F2B9
    DIM DIM F18B; DTE DTE E884; END END F18E; ERASE ERASE F2B7
    ERROR ERROR F1B4; FEED FEED F0B0; FILES FILES F098; FOR FOR F1A5
    GCURSOR GCURSOR F093; GLCURSOR GLCURSOR E682; GOSUB GOSUB F194; GOTO GOTO F192
    GPRINT GPRINT F09F; GRAD GRAD F186; GRAPH GRAPH E681; IF IF F196
    INIT INIT F294; INPUT INPUT F091; KEY KEY F285; KILL KILL F287
    LCURSOR LCURSOR F0A5; LET LET F198; LF LF F0B6; LFILES LFILES F0A0
    LINE LINE F099; LIST LIST F090; LLINE LLINE F0B7; LLIST LLIST F0B8
    LOAD LOAD F295; LOCK LOCK F1B5; LPRINT LPRINT F0B9; MAXFILES MAXFILES F288
    MERGE MERGE F08F; MODE MODE F2B3; NAME NAME F297; NEW NEW F19B
    NEXT NEXT F19A; OFF OFF F19E; ON ON F19C; OPEN OPEN F296
    OPN OPN F19D; OUT OUT F28A; PAPER PAPER E381; PASS PASS F2B8
    PAUSE PAUSE F1A2; PCONSOLE PCONSOLE F2B1; PHONE PHONE F2A0; PITCH PITCH F0A4
    POKE POKE F28C; POWER POWER F28B; PRESET PRESET F09A; PRINT PRINT F097
    PSET PSET F09B; PZONE PZONE F2B4; RADIAN RADIAN F1AA; RANDOM RANDOM F1A8
    READ READ F1A6; REM REM F1AB; RENUM RENUM F2B5; RESTORE RESTORE F1A7
    RESUME RESUME F28D; RETI RETI F28E; RETURN RETURN F199; RLINE RLINE F0BA
    RMT RMT E7A9; ROTATE ROTATE E685; RUN RUN F1A4; SAVE SAVE F299
    SET SET F298; SETCOM SETCOM E882; SETDEV SETDEV E886; SNDBRK SNDBRK F2A1
    SORGN SORGN E684; STOP STOP F1AC; TAB TAB F0BB; TERMINAL TERMINAL E883
    TEST TEST F0BC; TEXT TEXT E686; TITLE TITLE F2BA; TRANSMIT TRANSMIT E885
    TROFF TROFF F1B0; TRON TRON F1AF; UNLOCK UNLOCK F1B6; USING USING F085
    WAIT WAIT F1B3; XCALL XCALL F18A; XPOKE XPOKE F1A1; XPOKE# XPOKE# F1A0
    ZONE ZONE F0B4; AND AND F150; MOD MOD F250; NOT NOT F16D
    OR OR F151; XOR XOR F251; APPEND APPEND F2BF; AS AS F2BD
    ELSE ELSE F283; OUTPUT OUTPUT F2BE; STEP STEP F1AD; THEN THEN F1AE
    TO TO F1B1
"""


# --------------------------------------------------------------------------
# PC-125x family ("OLD" token group: PC-1245 ... PC-1255, PC-1150, PC-1210..1212)
# --------------------------------------------------------------------------
# Single-byte tokens, a different character code (letters 51..6A, digits
# 40..49, space 11) and lines stored as  E0+hundreds, BCD tens/units, body, 00.
# Token codes: read out of the Pocket Tools 2.1 program bas2img.exe (OLD group)
# and checked against 19 real PC-1251 tape recordings (about 670 lines): every
# token and character code that occurs there agrees.  One exception: the exe
# lists VAL as FE, the recordings show 7E, which is used here.
OLD_TOKENS = {
    0x7D: "ASC", 0x7E: "VAL", 0x7F: "LEN", 0x81: "AND", 0x82: ">=", 0x83: "<=",
    0x84: "<>", 0x85: "OR", 0x86: "NOT", 0x87: "SQR", 0x88: "CHR$", 0x89: "COM$",
    0x8A: "INKEY$", 0x8B: "STR$", 0x8C: "LEFT$", 0x8D: "RIGHT$", 0x8E: "MID$",
    0x90: "TO", 0x91: "STEP", 0x92: "THEN", 0x93: "RANDOM", 0x95: "WAIT", 0x96: "ERROR",
    0x99: "KEY", 0x9B: "SETCOM", 0x9C: "OPEN", 0x9D: "CLOSE", 0x9E: "ROM",
    0x9F: "LPRINT", 0xA0: "SIN", 0xA1: "COS", 0xA2: "TAN", 0xA3: "ASN", 0xA4: "ACS",
    0xA5: "ATN", 0xA6: "EXP", 0xA7: "LN", 0xA8: "LOG", 0xA9: "INT", 0xAA: "ABS",
    0xAB: "SGN", 0xAC: "DEG", 0xAD: "DMS", 0xAE: "RND", 0xAF: "PEEK", 0xB0: "RUN",
    0xB1: "NEW", 0xB2: "MEM", 0xB3: "LIST", 0xB4: "CONT", 0xB5: "DEBUG", 0xB6: "CSAVE",
    0xB7: "CLOAD", 0xB8: "MERGE", 0xB9: "TRON", 0xBA: "TROFF", 0xBB: "PASS",
    0xBC: "LLIST", 0xBD: "PI", 0xBE: "OUTSTAT", 0xBF: "INSTAT", 0xC0: "GRAD",
    0xC1: "PRINT", 0xC2: "INPUT", 0xC3: "RADIAN", 0xC4: "DEGREE", 0xC5: "CLEAR",
    0xC9: "CALL", 0xCA: "DIM", 0xCB: "DATA", 0xCC: "ON", 0xCD: "OFF", 0xCE: "POKE",
    0xCF: "READ", 0xD0: "IF", 0xD1: "FOR", 0xD2: "LET", 0xD3: "REM", 0xD4: "END",
    0xD5: "NEXT", 0xD6: "STOP", 0xD7: "GOTO", 0xD8: "GOSUB", 0xD9: "CHAIN",
    0xDA: "PAUSE", 0xDB: "BEEP", 0xDC: "AREAD", 0xDD: "USING", 0xDE: "RETURN",
    0xDF: "RESTORE",
}
# Names from the OLD table that belong to optional hardware / other models; they
# are decoded, but not recognised when tokenizing unless --ext is given.
# PC-1210/1211/1212: the "1211" group of bas2img.exe / bas2img.c (Pocket Tools 2.1)
# knows only these keywords (same codes as OLD_TOKENS).  Everything else, e.g.
# AND, OR, NOT, ASC, MID$, ON, DATA, POKE, PI, is not a keyword on these machines
# and stays plain letters when tokenizing.
P1211_NAMES = {
    ">=", "<=", "<>", "AREAD", "ABS", "ACS", "ASN", "ATN", "BEEP", "CHAIN", "CLEAR",
    "CLOAD", "CLOSE", "CONT", "COS", "CSAVE", "DEBUG", "DEGREE", "DEG", "DMS", "END",
    "EXP", "FOR", "GOSUB", "GOTO", "GRAD", "IF", "INPUT", "INT", "LN", "LET", "LIST",
    "LOG", "MEM", "NEXT", "NEW", "OPEN", "PAUSE", "PRINT", "RADIAN", "REM", "RETURN",
    "RUN", "SETCOM", "SGN", "SIN", "STEP", "STOP", "TAN", "THEN", "TO", "USING",
}
OLD_EXTRAS = {"COM$", "KEY", "ROM", "SETCOM", "OPEN", "CLOSE", "INSTAT", "OUTSTAT",
              "DEBUG", "ERROR"}
OLD_CHARS = {" ": 0x11, '"': 0x12, "?": 0x13, "!": 0x14, "#": 0x15, "%": 0x16,
             "$": 0x18, "\u03c0": 0x19, "\u221a": 0x1A, ",": 0x1B, ";": 0x1C,
             ":": 0x1D, "&": 0x1F, "(": 0x30, ")": 0x31, ">": 0x32, "<": 0x33,
             "=": 0x34, "+": 0x35, "-": 0x36, "*": 0x37, "/": 0x38, "^": 0x39,
             ".": 0x4A, "@": 0x1E, "\u00a5": 0x17, "~": 0x4D, "_": 0x4E}
for _i, _c in enumerate("0123456789"):
    OLD_CHARS[_c] = 0x40 + _i
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    OLD_CHARS[_c] = 0x51 + _i
OLD_CHARS_DEC = {v: k for k, v in OLD_CHARS.items()}
# 4B is the exponent "E" of 1E-8; it is shown as <4B>.
OLD_ENDMARK = 0xF0

# --------------------------------------------------------------------------
# PC-1280 / 1360 / 1470 / 1475 ("EXT" group): every keyword is a 2-byte token FE xx
# (all names: Pocket Tools 2.1, bas2img.c).  Same line layout as the PC-1403 family.
# Checked against the real reserve-key samples RSV1360.IMG / RSV1475.BIN / RSV1280.BIN
# of Pocket Tools (INPUT FE61, IF FE56, THEN FE54, GOTO FE2B, FOR FE57, TO FE52,
# STEP FE53, NEXT FE5B, LIST FE14, RUN FE10, PRINT FE60, USING FE2F, GOSUB FE62,
# RETURN FE65, DIM FE30, END FE5A, CSAVE FE20, CLOAD FE16).  Not tested against a
# complete program recorded on a real pocket.
# --------------------------------------------------------------------------
EXT2_CORE = {
    "RUN": 0xFE10, "NEW": 0xFE11, "CONT": 0xFE12, "PASS": 0xFE13, "LIST": 0xFE14,
    "LLIST": 0xFE15, "CLOAD": 0xFE16, "MERGE": 0xFE17, "LOAD": 0xFE18,
    "DELETE": 0xFE1B, "FILES": 0xFE1C, "CONVERT": 0xFE1E, "CSAVE": 0xFE20,
    "OPEN": 0xFE21, "CLOSE": 0xFE22, "SAVE": 0xFE23, "RANDOM": 0xFE25,
    "DEGREE": 0xFE26, "RADIAN": 0xFE27, "GRAD": 0xFE28, "BEEP": 0xFE29,
    "WAIT": 0xFE2A, "GOTO": 0xFE2B, "TRON": 0xFE2C, "TROFF": 0xFE2D, "CLEAR": 0xFE2E,
    "USING": 0xFE2F, "DIM": 0xFE30, "CALL": 0xFE31, "POKE": 0xFE32, "GPRINT": 0xFE33,
    "WIDTH": 0xFE38, "ERASE": 0xFE3A, "LFILES": 0xFE3B, "KILL": 0xFE3C,
    "FIELD": 0xFE48, "PUT": 0xFE49, "GET": 0xFE4A, "LSET": 0xFE4B, "RSET": 0xFE4C,
    "CLS": 0xFE50, "CURSOR": 0xFE51, "TO": 0xFE52, "STEP": 0xFE53, "THEN": 0xFE54,
    "ON": 0xFE55, "IF": 0xFE56, "FOR": 0xFE57, "LET": 0xFE58, "REM": 0xFE59,
    "END": 0xFE5A, "NEXT": 0xFE5B, "STOP": 0xFE5C, "READ": 0xFE5D, "DATA": 0xFE5E,
    "PRINT": 0xFE60, "INPUT": 0xFE61, "GOSUB": 0xFE62, "LPRINT": 0xFE64,
    "RETURN": 0xFE65, "RESTORE": 0xFE66, "CIRCLE": 0xFE6F, "PAINT": 0xFE70,
    "OUTPUT": 0xFE71, "APPEND": 0xFE72, "AS": 0xFE73, "MDF": 0xFE80, "REC": 0xFE81,
    "POL": 0xFE82, "TEN": 0xFE86, "RCP": 0xFE87, "SQU": 0xFE88, "CUR": 0xFE89,
    "HSN": 0xFE8A, "HCS": 0xFE8B, "HTN": 0xFE8C, "AHS": 0xFE8D, "AHC": 0xFE8E,
    "AHT": 0xFE8F, "FACT": 0xFE90, "LN": 0xFE91, "LOG": 0xFE92, "EXP": 0xFE93,
    "SQR": 0xFE94, "SIN": 0xFE95, "COS": 0xFE96, "TAN": 0xFE97, "INT": 0xFE98,
    "ABS": 0xFE99, "SGN": 0xFE9A, "DEG": 0xFE9B, "DMS": 0xFE9C, "ASN": 0xFE9D,
    "ACS": 0xFE9E, "ATN": 0xFE9F, "RND": 0xFEA0, "AND": 0xFEA1, "OR": 0xFEA2,
    "NOT": 0xFEA3, "PEEK": 0xFEA4, "XOR": 0xFEA5, "PI": 0xFEAE, "EOF": 0xFEB0,
    "LOF": 0xFEB2, "NCR": 0xFEB6, "NPR": 0xFEB7, "CUB": 0xFEBF, "ASC": 0xFED0,
    "VAL": 0xFED1, "LEN": 0xFED2, "KLEN": 0xFED3, "AKCNV$": 0xFEE0, "KACNV$": 0xFEE1,
    "JIS$": 0xFEE2, "INKEY$": 0xFEE9, "MID$": 0xFEEA, "LEFT$": 0xFEEB,
    "RIGHT$": 0xFEEC, "KMID$": 0xFEED, "KLEFT$": 0xFEEE, "KRIGHT$": 0xFEEF,
    "CHR$": 0xFEF0, "STR$": 0xFEF1, "HEX$": 0xFEF2,
}
# Names from the E500/EXT part of the table (AUTO, SET, TEXT, PAUSE, CHAIN, ...);
# --no-ext leaves them out when tokenizing.
EXT2_E = {
    "RENUM": 0xFE19, "AUTO": 0xFE1A, "INIT": 0xFE1D, "CONSOLE": 0xFE24,
    "BASIC": 0xFE36, "TEXT": 0xFE37, "COPY": 0xFE3D, "NAME": 0xFE3E, "SET": 0xFE3F,
    "LTEXT": 0xFE40, "GRAPH": 0xFE41, "LF": 0xFE42, "CSIZE": 0xFE43, "COLOR": 0xFE44,
    "DEFDBL": 0xFE46, "DEFSNG": 0xFE47, "PAUSE": 0xFE5F, "CHAIN": 0xFE67,
    "LLINE": 0xFE6A, "RLINE": 0xFE6B, "GLCURSOR": 0xFE6C, "SORGN": 0xFE6D,
    "CROTATE": 0xFE6E, "ARUN": 0xFE74, "AUTOGOTO": 0xFE75, "ERROR": 0xFE78,
    "ROT": 0xFE83, "DECI": 0xFE84, "HEX": 0xFE85, "DSKF": 0xFEB1, "LOC": 0xFEB3,
    "ERN": 0xFEC0, "ERL": 0xFEC1, "OPEN$": 0xFEE8,
}
EXT2_SPECIFIC = {"AREAD": 0xFE63, "MEM": 0xFEAF}
EXT2_1360 = {"GCURSOR": 0xFE68, "LINE": 0xFE69, "POINT": 0xFEAD, "PRESET": 0xFE35,
             "PSET": 0xFE34}                      # PC-1360 only (not 1475)
EXT2_1470 = {"AER": 0xFEBE}
EXT2_REM = 0xFE59
EXT2_SKIP = {"LOCATE", "RANDOMIZE"}               # aliases of CURSOR / RANDOM (E/G series)
_MODEL = [0]                                      # set by resolve_model

# PC-E500 family ("E" group: E500, E500S, E550, E650, U6000, PC-1480U, PC-1490U) and
# PC-E200/E220/G801-G850 ("G" group).  Same FE xx tokens, plus a few special bytes:
#   1F hi lo    fixed line number (GOTO/GOSUB/THEN/...)
#   1D ...      binary (BCD) numeric constant, written by the pocket itself
#   1E n        skip distance (E500 only, after REM or '), 1C hi lo  long jump / label
#   00 lo hi    absolute jump target (E500 only, written by the pocket at run time)
FE_G_ONLY = {"BSAVE": 0xFE20, "BLOAD": 0xFE16, "FIX": 0xFEC7, "LNINPUT": 0xFE63,
             "VDEG": 0xFED3, "DMS$": 0xFEF3, "HDCOPY": 0xFE4C, "INP": 0xFEA6,
             "LCOPY": 0xFE1F, "MOD": 0xFEC6, "MON": 0xFE0F, "OUT": 0xFE45,
             "PIOGET": 0xFEA8, "PIOSET": 0xFE48, "PIOPUT": 0xFE49, "RENUM": 0xFE17,
             "SPOUT": 0xFE4A, "SPINP": 0xFE4B}
FE_G_ALIAS = {"HEX": 0xFEF2, "MEM": 0xFEAF, "PAUSE": 0xFE60}   # tokenizing only
FE_E_ONLY = {"AER": 0xFEBE, "BDATA$": 0xFE0C, "BTEXT$": 0xFE0B, "EVAL": 0xFEA7,
             "KEY": 0xFE79, "MEM$": 0xFE0D, "RESUME": 0xFE77}
FE_EG = {"CASE": 0xFE7D, "DEFAULT": 0xFE7E, "ELSE": 0xFE76, "ENDIF": 0xFE4D,
         "ENDSWITCH": 0xFE7F, "FRE": 0xFEAF, "GCURSOR": 0xFE68, "LINE": 0xFE69,
         "POINT": 0xFEAD, "PRESET": 0xFE35, "PSET": 0xFE34, "REPEAT": 0xFE4E,
         "SWITCH": 0xFE7C, "UNTIL": 0xFE4F, "WEND": 0xFE7B, "WHILE": 0xFE7A}
FAMILYFE = ("EXT", "E", "G")


def fe_names(group, model=0, use_ext=True, all_models=False):
    """code -> keyword name for the FE xx families.  all_models: for decoding,
    accept the names of every model of the group."""
    if group == "EXT":
        d = {c: n for n, c in EXT2_CORE.items() if n not in EXT2_SKIP}
        d.update({c: n for n, c in EXT2_SPECIFIC.items()})
        if use_ext:
            d.update({c: n for n, c in EXT2_E.items()})
        if all_models or model == 1360:
            d.update({c: n for n, c in EXT2_1360.items()})
        if all_models or model == 1470:
            d.update({c: n for n, c in EXT2_1470.items()})
        return d
    d = {c: n for n, c in EXT2_CORE.items() if n not in ("CURSOR", "RANDOM")}
    if group == "E":
        d.update({c: n for n, c in EXT2_E.items()})
        d.update({c: n for n, c in FE_E_ONLY.items()})
    else:
        for n, c in FE_G_ONLY.items():
            if n in ("BLOAD", "BSAVE") and model != 852:
                continue
            d[c] = n
    d.update({c: n for n, c in FE_EG.items()})
    return d


def fe_keywords(group, model=0, use_ext=True):
    """[(NAME, bytes)] for tokenizing, longest first."""
    kws = {}
    for code, name in fe_names(group, model, use_ext).items():
        kws[name] = bytes([code >> 8, code & 0xFF])
    if group == "G":
        for name, code in FE_G_ALIAS.items():
            kws.setdefault(name, bytes([code >> 8, code & 0xFF]))
        if model != 852:
            kws.pop("BLOAD", None); kws.pop("BSAVE", None)
    return sorted(kws.items(), key=lambda kv: (-len(kv[0]), kv[0]))


# token classes (bas2img.c TokenType): which tokens may be followed by a line number
FE_LBL = {0xFE1B, 0xFE15, 0xFE19, 0xFE67, 0xFE74, 0xFE1A, 0xFE75, 0xFE62, 0xFE2B,
          0xFE14, 0xFE66, 0xFE77, 0xFE10, 0xFE54, 0xFE76}
FE_LST = {0xFE55, 0xFE1B, 0xFE15, 0xFE19, 0xFE67}
FE_ELSE = 0xFE76


def fe_number(body, i):
    """Decode a 1D numeric constant (E-series BCD).  Returns (text, next_index) or None."""
    n = len(body)
    if i + 2 >= n:
        return None
    fplen = 20 if body[i + 1] != 0 else 10
    exp = body[i + 2] - 256 if body[i + 2] > 127 else body[i + 2]
    nbytes = fplen // 2
    if i + 3 + nbytes > n:
        return None
    dig = []
    for b in body[i + 3:i + 3 + nbytes]:
        dig += [b >> 4, b & 15]
    last = 0
    for k, dv in enumerate(dig):
        if dv:
            last = k
    uexp = abs(exp)
    out = ""
    if -20 < exp < 0:
        out = "0." + "0" * max(uexp - 1, 0) + "".join(str(d) for d in dig[:last + 1])
        if fplen == 20:
            out += "#"
    elif 0 <= exp < 10:
        last = max(last, uexp)
        for k in range(last + 1):
            if k == uexp + 1:
                out += "."
            out += str(dig[k])
        if fplen > 10:
            out += "#"
    else:
        out = str(dig[0]) + "." + "".join(str(d) for d in dig[1:last + 1])
        out += ("D" if fplen > 10 else "E") + ("+" if exp > 0 else "-") \
            + f"{uexp // 10}{uexp % 10}"
    return out, i + 3 + nbytes


def detokenize_body_fe(body, names, group, jump=None):
    """FE xx families -> (text, used, unknown).  Never raises on odd bytes."""
    pieces, used, unknown = [], set(), set()
    n, i = len(body), 0
    in_str = rem = False
    eg = group in ("E", "G")

    def ch(b):
        return chr(b) if 32 <= b < 127 else f"<{b:02X}>"

    def drop_colon():
        if pieces and pieces[-1] == ("txt", ":"):
            pieces.pop()

    while i < n:
        b = body[i]
        if rem:
            pieces.append(("txt", ch(b)))
            i += 1
            continue
        if in_str:
            if b == 0x22:
                in_str = False
            pieces.append(("txt", ch(b)))
            i += 1
            continue
        if b == 0x22:
            in_str = True
            pieces.append(("txt", '"'))
            i += 1
        elif b == 0x27 and eg:                    # ' = REM character
            drop_colon()
            pieces.append(("txt", "'"))
            rem = True
            i += 1
            if group == "E" and i + 1 < n and body[i] == 0x1E:
                i += 2
        elif b == 0x1D and i + 2 < n and (r := fe_number(body, i)):
            pieces.append(("txt", r[0]))
            i = r[1]
        elif b == 0x1E and i + 1 < n and group == "E":
            i += 2
        elif b == 0x1C and i + 2 < n and eg:
            i += 3
        elif b == 0x1F and i + 2 < n:
            pieces.append(("txt", str((body[i + 1] << 8) | body[i + 2])))
            i += 3
        elif b == 0x00 and group == "E" and i + 2 < n:
            addr = body[i + 1] | (body[i + 2] << 8)
            num = jump(addr) if jump else None
            pieces.append(("txt", str(num) if num is not None
                           else f"<00><{body[i + 1]:02X}><{body[i + 2]:02X}>"))
            i += 3
        elif b == 0xFE and i + 1 < n:
            code = 0xFE00 | body[i + 1]
            name = names.get(code)
            if name is None:
                pieces.append(("txt", f"<FE><{body[i + 1]:02X}>"))
                unknown.add(code)
            else:
                if code == FE_ELSE and eg:
                    drop_colon()
                pieces.append(("kw", name))
                used.add(code)
                if code == EXT2_REM:
                    rem = True
                    if group == "E" and i + 3 < n and body[i + 2] == 0x1E:
                        i += 2
            i += 2
        else:
            pieces.append(("txt", ch(b)))
            if b >= 0x80:
                unknown.add(b)
            i += 1
    return join_pieces(pieces), used, unknown


def _raw_rest(rest):
    out = bytearray()
    j = 0
    while j < len(rest):
        m = HEX2.match(rest, j)
        if m:
            out.append(int(m.group(1), 16))
            j += 4
        else:
            out += rest[j].encode("latin-1", errors="replace")
            j += 1
    return bytes(out)


def tokenize_text_fe(text, keywords, group):
    """One BASIC line (without number) -> body bytes for EXT / E / G groups."""
    out = bytearray()
    i, n = 0, len(text)
    in_string = False
    eg = group in ("E", "G")
    rem_tok = bytes([EXT2_REM >> 8, EXT2_REM & 0xFF])

    def rem_rest(rest):
        if rest.startswith(" "):
            rest = rest[1:]
        raw = _raw_rest(rest)
        if group == "E":
            out.extend([0x1E, (len(raw) + 2) & 0xFF])
        out.extend(raw)

    while i < n:
        c = text[i]
        m = HEX2.match(text, i)
        if m:
            out.append(int(m.group(1), 16))
            i += 4
            continue
        if in_string:
            if c == '"':
                in_string = False
            out += c.encode("latin-1", errors="replace")
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(0x22)
            i += 1
            continue
        if c == " ":
            if eg:
                out.append(0x20)
            i += 1
            continue
        if c == "&":
            j = i + 1
            while j < n and text[j] in HEXDIG:
                j += 1
            out += text[i:j].upper().encode("ascii")
            i = j
            continue
        if eg and c == "*" and (not out.strip() or out[-1:] == b":"):
            j = i + 1                                    # label: no keywords inside
            while j < n and (text[j].isalnum() or text[j] in "_@"):
                j += 1
            out += text[i:j].upper().encode("latin-1", errors="replace")
            i = j
            continue
        if c == "'":
            if eg:
                if out[-1:] != b":":
                    out.append(0x3A)
                out.append(0x27)
                rem_rest_b = text[i + 1:]
                raw = _raw_rest(rem_rest_b)
                if group == "E":
                    out.extend([0x1E, (len(raw) + 2) & 0xFF])
                out.extend(raw)
            else:
                out += rem_tok
                rem_rest(text[i + 1:])
            return bytes(out)
        for name, code in keywords:
            if text[i:i + len(name)].upper() == name:
                if code == rem_tok:
                    out += code
                    rem_rest(text[i + len(name):])
                    return bytes(out)
                if eg and code == bytes([FE_ELSE >> 8, FE_ELSE & 0xFF]) and out[-1:] != b":":
                    out.append(0x3A)
                out += code
                i += len(name)
                if ((code[0] << 8) | code[1]) in FE_LBL:      # drop blanks before the number
                    j = i
                    while j < n and text[j] == " ":
                        j += 1
                    if j < n and text[j].isdigit():
                        i = j
                break
        else:
            out += c.upper().encode("latin-1", errors="replace")
            i += 1
    return bytes(out)


def compile_jump_numbers(b, group):
    """Fixed line numbers after GOTO/GOSUB/THEN/... -> 1F hi lo (bas2img CompileFixedJumpNb)."""
    out = bytearray()
    n, i = len(b), 0
    bracket = 0
    in_str = rem = False
    token_lst = False
    ttype_lbl = False
    eg = group in ("E", "G")
    while i < n:
        byte = b[i]
        i += 1
        out.append(byte)
        if byte == 0x3A:
            token_lst, bracket = False, 0
        elif byte == 0x28:
            bracket += 1
        elif byte == 0x29 and bracket > 0:
            bracket -= 1
        elif byte == 0x22:
            in_str = not in_str
        elif byte == 0x27 and eg:
            rem = True
        if rem or in_str:
            while i < n:
                byte = b[i]
                i += 1
                out.append(byte)
                if not rem and byte == 0x22:
                    in_str = False
                    break
            continue
        is_comma = byte == 0x2C and token_lst and bracket == 0
        if (byte == 0xFE and i < n) or is_comma:
            if not is_comma:
                token = 0xFE00 | b[i]
                out.append(b[i])
                i += 1
                if token == EXT2_REM:
                    rem = True
                    continue
                ttype_lbl = token in FE_LBL
                if token in FE_LST:
                    token_lst = True
            if i >= n:
                break
            if ttype_lbl:
                j = i
                while j < n and 0x30 <= b[j] <= 0x39:
                    j += 1
                nxt = b[j] if j < n else 0
                if j > i and (nxt in (0, 0x3A) or (nxt == 0x2C and token_lst)):
                    num = int(b[i:j])
                    if num > 65279:
                        raise ValueError(f"line number {num} is too large")
                    out += bytes([0x1F, num >> 8, num & 0xFF])
                    i = j
    return bytes(out)


def tokenize_listing_fe(text, keywords, group):
    lines = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            raise ValueError(f"line without a line number: {raw!r}")
        no = int(m.group(1))
        if not 1 <= no <= 65279:
            raise ValueError(f"line number out of range: {no}")
        if no in lines:
            raise ValueError(f"duplicate line number {no}")
        body = compile_jump_numbers(tokenize_text_fe(m.group(2), keywords, group), group)
        if len(body) + 1 > 0xFF:
            raise ValueError(f"line {no} is too long ({len(body) + 1} bytes, max 255)")
        lines[no] = body
    return sorted(lines.items())


import argparse
import re


# --------------------------------------------------------------------------
# Line body -> text  (detokenizer)
# --------------------------------------------------------------------------
def tokenize_body_pieces(body, use_ext=True, group="NEW3"):
    """Return (pieces, used, unknown); pieces are ('kw', text) / ('txt', text)."""
    pieces = []
    used, unknown = set(), set()
    in_string = False
    i = 0
    n = len(body)
    while i < n:
        b = body[i]

        if b == 0x22:                       # "
            in_string = not in_string
            pieces.append(("txt", '"'))
            i += 1
            continue

        if in_string:
            pieces.append(("txt", chr(b) if 32 <= b < 127 else f"<{b:02X}>"))
            i += 1
            continue

        if use_ext and b == 0xEF and i + 1 < n and body[i + 1] in EXT_TOKENS:
            pieces.append(("kw", EXT_TOKENS[body[i + 1]]))
            used.add((0xEF, body[i + 1]))
            i += 2
            continue

        if b in TOKENS:
            pieces.append(("kw", TOKENS[b]))
            used.add(b)
            i += 1
            continue

        if b >= 0x80:
            pieces.append(("txt", f"<{b:02X}>"))
            unknown.add(b)
            i += 1
            continue

        pieces.append(("txt", chr(b) if 32 <= b < 127 else f"<{b:02X}>"))
        i += 1

    return pieces, used, unknown


def join_pieces(pieces):
    """Join pieces, putting a blank around keywords where they would
    otherwise run into neighbouring letters/digits."""
    out = []
    for idx, (kind, text) in enumerate(pieces):
        if kind == "kw":
            if out and (out[-1][-1].isalnum() or out[-1][-1] in '$)"#'):
                out.append(" ")
            out.append(text)
            nxt = pieces[idx + 1][1] if idx + 1 < len(pieces) else ""
            if nxt and (nxt[0].isalnum() or nxt[0] in '"&'):
                out.append(" ")
        else:
            out.append(text)
    return "".join(out)


def detokenize_body(body, use_ext=True, group="NEW3"):
    pieces, used, unknown = tokenize_body_pieces(body, use_ext, group)
    return join_pieces(pieces), used, unknown


# --------------------------------------------------------------------------
# Image reader
# --------------------------------------------------------------------------
def parse_from(data, start):
    """Parse line records beginning at offset `start`.

    Returns (records, ok); records are (line_no, declared_len, body, length_ok).
    Tolerant: when the declared length does not match (damaged files) the
    line ends at the next 0D.
    """
    records = []
    p = start
    last = -1
    n = len(data)
    while p + 3 <= n:
        if data[p] == EOP:
            break
        line_no = (data[p] << 8) | data[p + 1]
        if line_no <= last:
            return records, False
        length = data[p + 2]
        q = p + 3
        end = q + length - 1                 # index of the expected 0D
        if length >= 1 and end < n and data[end] == 0x0D:
            body, length_ok = data[q:end], True
        else:
            end = data.find(b"\x0d", q)
            if end < 0:
                return records, False
            body, length_ok = data[q:end], False
        records.append((line_no, length, bytes(body), length_ok))
        last = line_no
        p = end + 1
    return records, True


def read_image(data):
    """Find the start of the first line record automatically (the header
    length differs between tools).  Returns (records, start_offset)."""
    best, best_key, best_start = [], (-1, -1), 0
    for start in range(0, min(64, len(data))):
        recs, _ok = parse_from(data, start)
        if not recs or (recs[0][0] == 0 and len(recs) < 2):
            continue
        key = (len(recs), sum(1 for r in recs if r[3]))
        if key > best_key:
            best, best_key, best_start = recs, key, start
    return best, best_start


def parse_tolerant(data, start):
    """Like parse_from, but never gives up: out-of-order line numbers are accepted,
    a missing 0D takes the rest of the file.  Returns (records, warnings, end_offset)
    where end_offset is the first byte not used (end marker or garbage)."""
    records, warns = [], []
    p, n, last = start, len(data), -1
    while p + 3 <= n:
        if data[p] == EOP:
            break
        line_no = (data[p] << 8) | data[p + 1]
        length = data[p + 2]
        q = p + 3
        end = q + length - 1
        if length >= 1 and end < n and data[end] == 0x0D:
            body, ok = data[q:end], True
        else:
            end = data.find(b"\x0d", q)
            if end < 0:
                records.append((line_no, length, bytes(data[q:]), False))
                warns.append(f"line {line_no}: no end-of-line byte, took the rest of the file")
                return records, warns, n
            body, ok = data[q:end], False
        if line_no <= last:
            warns.append(f"line {line_no} (offset {p}): line number out of order")
        records.append((line_no, length, bytes(body), ok))
        last = max(last, line_no)
        p = end + 1
    return records, warns, p


# --------------------------------------------------------------------------
# Text -> line body  (tokenizer)
# --------------------------------------------------------------------------
HEX2 = re.compile(r"<([0-9A-Fa-f]{2})>")
HEXDIG = "0123456789ABCDEFabcdef"


def build_keywords(use_ext, group="NEW3"):
    """[(KEYWORD, bytes)] sorted longest first."""
    kws = {}
    if group == "EXT":
        for code, name in ext2_names(bool(use_ext)).items():
            kws[name] = bytes([code >> 8, code & 0xFF])
        return sorted(kws.items(), key=lambda kv: (-len(kv[0]), kv[0]))
    for code, name in TOKENS.items():
        kws[name] = bytes([code])
    if use_ext:
        for code, name in EXT_TOKENS.items():
            kws.setdefault(name, bytes([0xEF, code]))
    return sorted(kws.items(), key=lambda kv: (-len(kv[0]), kv[0]))


def tokenize_text(text, keywords, rem_raw=True, rem=bytes([0xD7])):
    """Convert the text of one line (without line number) to its body bytes
    (without the terminating 0D)."""
    out = bytearray()
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]

        m = HEX2.match(text, i)
        if m:                                  # <XX> escape from detokenizer
            out.append(int(m.group(1), 16))
            i += 4
            continue

        if in_string:
            if c == '"':
                in_string = False
            out.append(ord(c) & 0xFF)
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(0x22)
            i += 1
            continue

        if c == " ":
            i += 1
            continue

        if c == "&":                           # hex number: no keywords inside
            j = i + 1
            while j < n and text[j] in HEXDIG:
                j += 1
            out += text[i:j].upper().encode("ascii")
            i = j
            continue

        for name, code in keywords:
            if text[i:i + len(name)].upper() == name:
                out += code
                i += len(name)
                if code == rem and rem_raw:    # REM: rest of the line is raw
                    rest = text[i:]
                    if rest.startswith(" "):   # the detokenizer adds one blank after REM
                        rest = rest[1:]
                    out += rest.encode("latin-1", errors="replace")
                    return bytes(out)
                break
        else:
            out.append(ord(c.upper()) & 0xFF)   # outside strings: upper case
            i += 1
    return bytes(out)


LINE_RE = re.compile(r"^\s*(\d+)\s?(.*)$")


def tokenize_listing(text, keywords, rem_raw=True, rem=bytes([0xD7])):
    """Return [(line_no, body)] from a BASIC text listing."""
    lines = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            raise ValueError(f"line without a line number: {raw!r}")
        no = int(m.group(1))
        if not 1 <= no < 0xFF00:
            raise ValueError(f"line number out of range: {no}")
        if no in lines:
            raise ValueError(f"duplicate line number {no}")
        body = tokenize_text(m.group(2), keywords, rem_raw, rem)
        if len(body) + 1 > 0xFF:
            raise ValueError(f"line {no} is too long ({len(body) + 1} bytes, max 255)")
        lines[no] = body
    return sorted(lines.items())


def build_image(records, header=b"", endmark=True):
    out = bytearray(header)
    for no, body in records:
        out += bytes([no >> 8, no & 0xFF, len(body) + 1]) + body + b"\x0d"
    if endmark:
        out.append(EOP)
    return bytes(out)


# --------------------------------------------------------------------------
# PC-1500 / PC-1600 family
# --------------------------------------------------------------------------
FAMILY15 = ("PC1500", "PC1600")


def _load_pool(data):
    pool = []
    for chunk in data.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if chunk:
            name, abbr, code = chunk.split()
            pool.append((name, abbr, int(code, 16)))
    return pool


class Registry:
    """Keyword registry of one PC-1500 / PC-1600 family (port of the lookup
    rules described above: later pool entries win)."""

    def __init__(self, pool, dotted):
        self.by_name = {}          # NAME and "ABBR." forms -> (name, code)
        self.by_code = {}          # code -> name
        self.high = set()          # first bytes of 2-byte tokens
        first = {}
        last = {n: i for i, (n, _a, _c) in enumerate(pool)}
        for i, (name, abbr, code) in enumerate(pool):
            self.by_name[name] = (name, code)
            if dotted:
                for ln in range(len(abbr), len(name)):
                    self.by_name[name[:ln] + "."] = (name, code)
            self.by_code[code] = name
            self.high.add(code >> 8)
            if last[name] == i:
                first.setdefault(name[0], []).append((name, code))
        for lst in first.values():
            lst.sort(key=lambda t: -len(t[0]))     # stable: longest name first
        self.first = first

    def lookup(self, word):
        return self.by_name.get(word.upper())

    def longest_prefix(self, rest):
        """rest: bytes starting with an upper-case letter."""
        for name, code in self.first.get(chr(rest[0]), ()):
            if rest.startswith(name.encode("ascii")):
                return name, code
        return None


REM15 = 0xF1AB
TARGET_KEYWORDS = ("GOTO", "GOSUB", "THEN", "RESUME", "RUN", "RESTORE")
_registries = {}


def registry_for(group):
    if group not in _registries:
        if group == "PC1500":
            _registries[group] = Registry(_load_pool(_PC1500_DATA), dotted=True)
        else:   # the PC-1600 set defines no dotted abbreviations
            _registries[group] = Registry(_load_pool(_PC1600_DATA), dotted=False)
    return _registries[group]


def _char15(b):
    """Printable text for one literal byte (CP437 for 80..FF), or <XX>."""
    if 32 <= b < 127:
        return chr(b)
    if b >= 0x80:
        return bytes([b]).decode("cp437")
    return f"<{b:02X}>"


def _lit15(body, i, allow_high):
    b = body[i]
    if b == 0x3C and i + 3 < len(body) and body[i + 3] == 0x3E and \
            all(chr(x) in HEXDIG for x in body[i + 1:i + 3]):
        return "<3C>"                         # a literal "<AB>" must not read as an escape
    if b >= 0x80 and not allow_high:
        return f"<{b:02X}>"
    return _char15(b)


def detokenize_body15(body, reg, is1600):
    pieces, used, unknown = [], set(), set()
    in_string = False
    i, n = 0, len(body)
    while i < n:
        b = body[i]
        if b == 0x22:
            in_string = not in_string
            pieces.append(("txt", '"'))
            i += 1
        elif in_string:
            pieces.append(("txt", _lit15(body, i, True)))
            i += 1
        elif b == 0x27:                       # ' = REM shorthand, rest is raw
            pieces.append(("txt", "'"))
            pieces += [("txt", _lit15(body, j, True)) for j in range(i + 1, n)]
            break
        elif b in reg.high and i + 1 < n:
            code = (b << 8) | body[i + 1]
            name = reg.by_code.get(code)
            if name is None:
                pieces.append(("txt", f"<{b:02X}>"))
                unknown.add(b)
                i += 1
            elif code == REM15:
                pieces.append(("kw", "REM"))
                pieces += [("txt", _lit15(body, j, True)) for j in range(i + 2, n)]
                used.add(code)
                break
            else:
                pieces.append(("kw", name))
                used.add(code)
                i += 2
        elif is1600 and b == 0x1F and i + 3 < n and body[i + 3] == 0x00:
            pieces.append(("txt", str((body[i + 1] << 8) | body[i + 2])))
            i += 4
        else:
            if b >= 0x80:
                unknown.add(b)
            pieces.append(("txt", _lit15(body, i, False)))
            i += 1
    return join_pieces15(pieces), used, unknown


def join_pieces15(pieces):
    """Like join_pieces, but text after REM / ' is raw and is never re-spaced."""
    out = []
    for idx, (kind, text) in enumerate(pieces):
        if kind == "kw" and text == "REM":
            if out and (out[-1][-1].isalnum() or out[-1][-1] in '$)"#'):
                out.append(" ")
            out.append("REM")
            continue
        if kind == "kw":
            if out and (out[-1][-1].isalnum() or out[-1][-1] in '$)"#'):
                out.append(" ")
            out.append(text)
            nxt = pieces[idx + 1][1] if idx + 1 < len(pieces) else ""
            if nxt and (nxt[0].isalnum() or nxt[0] in '"&'):
                out.append(" ")
        else:
            out.append(text)
    return "".join(out)


def parse15_from(data, start):
    """Records of a PC-1500/1600 image: (line_no, declared_len, body, length_ok)
    or ('SEGMENT',) markers.  Ends at 00 00, FF alone at the end, or EOF."""
    records, p, last, n = [], start, -1, len(data)
    while p + 1 < n:
        if data[p] == 0 and data[p + 1] == 0:
            break
        if data[p] == 0xFF:
            records.append(None)               # segment boundary
            p += 3 if data[p:p + 3] == b"\xff\x00\x00" else 1
            last = -1
            continue
        if p + 2 >= n:
            return records, False
        line_no = (data[p] << 8) | data[p + 1]
        if line_no <= last:
            return records, False
        length, q = data[p + 2], p + 3
        end = q + length - 1
        if length >= 1 and end < n and data[end] == 0x0D:
            body, ok = data[q:end], True
        else:
            end = data.find(b"\x0d", q)
            if end < 0:
                return records, False
            body, ok = data[q:end], False
        records.append((line_no, length, bytes(body), ok))
        last, p = line_no, end + 1
    return records, True


def read_image15(data, offset=None):
    """Return (records, start).  `offset` forces the first-line position,
    otherwise it is searched (0..63)."""
    starts = [offset] if offset is not None else range(0, min(64, len(data)))
    best, best_key, best_start = [], (-1, -1), 0
    for s in starts:
        recs, _ok = parse15_from(data, s)
        lines = [r for r in recs if r is not None]
        if not lines or lines[0][0] == 0:
            continue
        key = (len(lines), sum(1 for r in lines if r[3]))
        if key > best_key:
            best, best_key, best_start = recs, key, s
    return best, best_start


def expand_abbrev(line, reg):
    """Expand dotted abbreviations (P. -> PRINT).  Not done in strings, after
    REM or after '."""
    res, word, state = "", "", "N"

    def is_rem_start(s):
        if len(s) < 3 or s[-3:].upper() != "REM":
            return False
        return len(s) == 3 or s[-4] == ":" or s[-4].isdigit()

    for c in line:
        if state == "N":
            if c == '"':
                res += word + c
                word, state = "", "S"
            elif c.isascii() and c.isalpha():
                word += c
            elif c == "." and word:
                hit = reg.lookup(word + ".")
                if hit:
                    res += hit[0]
                else:
                    for sl in range(len(word) - 1, 0, -1):
                        suffix = word[-sl:] + "."
                        hit = reg.lookup(suffix)
                        if hit:
                            res += word[:-sl]
                            if is_rem_start(res):
                                state = "C"
                                res += suffix
                            else:
                                res += hit[0]
                            break
                    else:
                        res += word + "."
                word = ""
                if state == "N" and is_rem_start(res):
                    state = "C"
            else:
                res += word
                word = ""
                if c == "'" or is_rem_start(res):
                    state = "C"
                res += c
        elif state == "S":
            res += c
            if c == '"':
                state = "N"
        else:
            res += c
    return res + word


def encode_cp437(text):
    out, i = bytearray(), 0
    while i < len(text):
        m = HEX2.match(text, i)
        if m:
            out.append(int(m.group(1), 16))
            i += 4
            continue
        try:
            out += text[i].encode("cp437")
        except UnicodeEncodeError:
            out.append(0x3F)
        i += 1
    return bytes(out)


def scan_line15(raw, reg, is1600):
    out, i, n = bytearray(), 0, len(raw)
    in_string, expect = False, False
    while i < n:
        b = raw[i]
        if in_string:
            out.append(b)
            i += 1
            if b == 0x22:
                in_string = False
            continue
        if b == 0x20:
            i += 1
            continue
        was, expect = expect, False
        if is1600 and was and 0x30 <= b <= 0x39:
            j = i
            while j < n and 0x30 <= raw[j] <= 0x39 and j - i < 5:
                j += 1
            target = int(raw[i:j])
            if target <= 0xFFFF:
                out += bytes([0x1F, target >> 8, target & 0xFF, 0x00])
                i, expect = j, True
                continue
            out += raw[i:j]
            i = j
            continue
        if was and b == 0x2C:                  # comma inside an ON ... GOTO list
            out.append(b)
            i += 1
            expect = True
            continue
        if b == 0x27:                          # ' = REM shorthand
            out += raw[i:]
            break
        if b == 0x22:
            out.append(b)
            in_string = True
            i += 1
        elif b >= 0xE0:                        # already tokenized pair
            out += raw[i:i + 2]
            i += 2
        elif 0x41 <= b <= 0x5A:
            hit = reg.longest_prefix(raw[i:])
            if hit:
                name, code = hit
                out += bytes([code >> 8, code & 0xFF])
                i += len(name)
                if code == REM15:
                    out += raw[i:]
                    break
                if name in TARGET_KEYWORDS:
                    expect = True
            else:
                out.append(b)
                i += 1
        else:
            out.append(b)
            i += 1
    return bytes(out)


def tokenize_listing15(text, reg, is1600):
    """Return a list of segments; each is [(line_no, body)] in ascending order."""
    segments, current, seen = [], [], set()
    for raw in text.split("\n"):
        line = raw.lstrip(" \t\r")
        stripped = line.rstrip(" \t\r")
        if stripped in ("#SEGMENT", "99999"):
            segments.append(current)
            current, seen = [], set()
            continue
        if not stripped or line.startswith("//") or line.startswith("#"):
            continue
        m = re.match(r"(\d+)(.*)$", line, re.S)
        if not m:
            raise ValueError(f"line without a line number: {stripped!r}")
        no = int(m.group(1))
        if not 1 <= no <= 0xFEFF:
            raise ValueError(f"line number out of range: {no}")
        if no in seen:
            raise ValueError(f"duplicate line number {no}")
        seen.add(no)
        rest = m.group(2).rstrip("\r")
        if reg is not None and not is1600:
            rest = expand_abbrev(rest, reg)
        body = scan_line15(encode_cp437(rest), reg, is1600)
        if len(body) + 1 > 0xFF:
            raise ValueError(f"line {no} is too long ({len(body) + 1} bytes, max 255)")
        current.append((no, body))
    segments.append(current)
    return [sorted(s) for s in segments]


def build_image15(segments, header=b"", endmark=False):
    out = bytearray(header)
    for k, seg in enumerate(segments):
        if k:
            out += b"\xff\x00\x00"
        for no, body in seg:
            out += bytes([no >> 8, no & 0xFF, len(body) + 1]) + body + b"\x0d"
    if endmark:
        out += b"\x00\x00"
    return bytes(out)



# --------------------------------------------------------------------------
# PC-125x family
# --------------------------------------------------------------------------
FAMILYOLD = ("OLD", "P1211")


def detokenize_body_old(body):
    pieces, used, unknown = [], set(), set()
    in_string = False
    for b in body:
        if b == 0x12:
            in_string = not in_string
            pieces.append(("txt", '"'))
        elif in_string:
            ch = OLD_CHARS_DEC.get(b)
            pieces.append(("txt", ch if ch and ch != '"' else f"<{b:02X}>"))
        elif b in OLD_TOKENS:
            name = OLD_TOKENS[b]
            used.add(b)
            pieces.append(("txt" if name[0] in "<>" else "kw", name))
        elif b in OLD_CHARS_DEC:
            pieces.append(("txt", OLD_CHARS_DEC[b]))
        else:
            pieces.append(("txt", f"<{b:02X}>"))
            unknown.add(b)
    # literal blanks stay inside strings only; join like the other families
    return join_pieces(pieces), used, unknown


def parse_old_from(data, start):
    """Records (line_no, declared_len, body, True) of a PC-125x image."""
    records, p, n = [], start, len(data)
    while p + 2 < n and 0xE0 <= data[p] <= 0xE9:
        lo = data[p + 1]
        if (lo >> 4) > 9 or (lo & 15) > 9:
            break
        line_no = (data[p] - 0xE0) * 100 + (lo >> 4) * 10 + (lo & 15)
        end = data.find(b"\x00", p + 2)
        if end < 0:
            records.append((line_no, 0, bytes(data[p + 2:]), False))
            break
        records.append((line_no, end - p - 1, bytes(data[p + 2:end]), True))
        p = end + 1
    return records, True


def deblock_tape(data):
    """Tape/Transfile style stream: ID byte 20, then blocks of 8 data bytes
    + 1 checksum byte -> plain bytes (header bytes included)."""
    out, i = bytearray(), 1
    while i < len(data):
        out += data[i:i + 8]
        i += 9
    return bytes(out)


def read_image_old(data, offset=None):
    starts = [offset] if offset is not None else range(0, min(80, len(data)))
    best, best_n, best_start = [], 0, 0
    for s in starts:
        recs, _ok = parse_old_from(data, s)
        if len(recs) > best_n:
            best, best_n, best_start = recs, len(recs), s
    return best, best_start


def build_keywords_old(include_extras, group="OLD"):
    kws = {}
    for code, name in OLD_TOKENS.items():
        if group == "P1211" and name not in P1211_NAMES:
            continue
        if include_extras or name not in OLD_EXTRAS:
            kws[name] = bytes([code])
    return sorted(kws.items(), key=lambda kv: (-len(kv[0]), kv[0]))


def tokenize_text_old(text, keywords, rem_raw=True):
    out, i, n = bytearray(), 0, len(text)
    in_string = False
    rem = bytes([0xD3])

    def put(ch):
        if ch in OLD_CHARS:
            out.append(OLD_CHARS[ch])
        else:
            raise ValueError(f"character {ch!r} has no PC-125x code (use <XX>)")

    while i < n:
        c = text[i]
        m = HEX2.match(text, i)
        if m:
            out.append(int(m.group(1), 16))
            i += 4
            continue
        if in_string:
            if c == '"':
                in_string = False
            put(c.upper() if c.isascii() else c)   # no lower case on these models
            i += 1
            continue
        if c == '"':
            in_string = True
            put(c)
            i += 1
            continue
        if c == " ":
            i += 1
            continue
        for name, code in keywords:
            if text[i:i + len(name)].upper() == name:
                out += code
                i += len(name)
                if code == rem and rem_raw:
                    rest = text[i:]
                    if rest.startswith(" "):
                        rest = rest[1:]
                    j = 0
                    while j < len(rest):          # raw: blanks kept, <XX> allowed
                        mm = HEX2.match(rest, j)
                        if mm:
                            out.append(int(mm.group(1), 16))
                            j += 4
                        else:
                            put(rest[j].upper() if rest[j].isascii() else rest[j])
                            j += 1
                    return bytes(out)
                break
        else:
            put(c.upper() if c.isascii() else c)
            i += 1
    return bytes(out)


def tokenize_listing_old(text, keywords, rem_raw=True):
    lines = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith(("//", "#")):
            continue
        m = LINE_RE.match(raw)
        if not m:
            raise ValueError(f"line without a line number: {raw!r}")
        no = int(m.group(1))
        if not 1 <= no <= 999:
            raise ValueError(f"line number out of range for this model (1-999): {no}")
        if no in lines:
            raise ValueError(f"duplicate line number {no}")
        lines[no] = tokenize_text_old(m.group(2), keywords, rem_raw)
    return sorted(lines.items())


def build_image_old(records, header=b"", endmark=False):
    out = bytearray(header)
    for no, body in records:
        out += bytes([0xE0 + no // 100, (no // 10 % 10) << 4 | no % 10]) + body + b"\x00"
    if endmark:
        out.append(OLD_ENDMARK)
    return bytes(out)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def parse_model(text):
    text = text.upper()
    if text.endswith("M2"):                      # E500M2 = 2nd character set
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"cannot read model number from {text!r}")
    return int(digits)


def resolve_model(text):
    """Return (group, detok_ext, tok_ext) or raise SystemExit with a message."""
    try:
        model = parse_model(text)
    except ValueError as e:
        raise SystemExit(str(e))
    group = MODEL_GROUPS.get(model)
    if group is None:
        raise SystemExit(f"Unknown model {text}. Known: "
                         + " ".join(str(m) for m in sorted(MODEL_GROUPS)))
    if group == "UNSUPPORTED":
        raise SystemExit(f"PC-{model} uses an older token table (group OLD/1211) "
                         "that this script does not have yet.")
    if model in (1210, 1211, 1212):
        print("note: PC-1210/1211/1212 use the PC-125x image layout and a reduced token "
              "set (source: Pocket Tools bas2img); not tested against a real PC-1211 "
              "recording.", file=sys.stderr)
    if group == "G" and model == 850 and "V" in text.upper().replace("G850", "", 1):
        model = 852
    _MODEL[0] = model
    if group in ("E", "G"):
        print("note: experimental PC-E/G support (token table and layout from Pocket Tools). "
              "Numeric constants stay ASCII when tokenizing"
              + (", and on the PC-E500 you must enter TEXT and then BASIC after loading "
                 "an image." if group == "E" else "."), file=sys.stderr)
    if group == "EXT":
        print("note: PC-1280/1360/1470/1475 use 2-byte FE xx tokens (Pocket Tools table, "
              "key tokens confirmed with its sample files); not tested with a full "
              "recording from a real pocket.", file=sys.stderr)
    det_ext, tok_ext, verified = GROUP_PROFILE[group]
    print(f"Model PC-{model} -> token group {group}"
          + ("" if verified else " (table reused from PC-1403, UNVERIFIED for this model)"),
          file=sys.stderr)
    return group, det_ext, tok_ext


# --------------------------------------------------------------------------
# Automatic model detection (det without --model)
# --------------------------------------------------------------------------
# One representative model per token group is tried and the best decoding
# wins.  Models inside a group cannot be told apart (1403 / 1425 / 1445 ...,
# 1360 / 1475, E500 / E650), but they share the token table, so the
# listing is the same.
_UNK = re.compile(r"<[0-9A-Fa-f]{2}>")
GUESS_ORDER = (("OLD", "1251"), ("PC1500", "1500"), ("PC1600", "1600"),
               ("EXT", "1360"), ("E", "E500"), ("G", "G850"), ("NEW3", "1403"))


def _score_text(lines, nbytes):
    """Lower is better: unmapped <XX> bytes weigh most, then odd looking lines."""
    text = "\n".join(lines)
    bad = len(_UNK.findall(text))
    return bad / max(1, nbytes)


def guess_group(data):
    """Return (group, representative_model) or (None, None)."""
    # 1. PC-125x family: E0..E9 line headers cover (nearly) the whole file
    recs, _s = read_image_old(data)
    if recs:
        used = sum(len(r[2]) + 3 for r in recs)
        if used >= 0.8 * len(data) - 8:
            if all(r[3] and len(r[2]) > 0 for r in recs):
                return "OLD", "1251"
    results = []
    # 2. PC-1500 / PC-1600 (2-byte tokens, segments)
    for group, model in (("PC1600", "1600"), ("PC1500", "1500")):
        try:
            reg = registry_for(group)
            r15, _st = read_image15(data)
            lines = [r for r in r15 if r is not None]
            if not lines or sum(r[3] for r in lines) < 0.5 * len(lines):
                continue
            texts, nb = [], 0
            for ln, _d, body, ok in lines:
                t, _u, _k = detokenize_body15(body, reg, group == "PC1600")
                texts.append(t)
                nb += len(body)
            results.append((_score_text(texts, nb), len(lines), group, model))
        except Exception:
            pass
    # 3. layouts "hi lo len body 0D": NEW3, EXT, E, G
    recs, start = read_image(data)
    if recs and sum(r[3] for r in recs) >= 0.5 * len(recs):
        for group, model in (("E", "E500"), ("G", "G850"), ("EXT", "1360"), ("NEW3", "1403")):
            try:
                _MODEL[0] = parse_model(model)
                ext, _a, _b = GROUP_PROFILE[group]
                names = fe_names(group, _MODEL[0], ext, True) if group in FAMILYFE else None
                texts, nb = [], 0
                for ln, _d, body, ok in recs:
                    if names is not None:
                        t, _u, _k = detokenize_body_fe(body, names, group, None)
                    else:
                        t, _u, _k = detokenize_body(body, ext, group)
                    texts.append(t)
                    nb += len(body)
                results.append((_score_text(texts, nb), len(recs), group, model))
            except Exception:
                pass
    if not results:
        return None, None
    order = [g for g, _m in GUESS_ORDER]
    # best score; on a tie the earlier entry of GUESS_ORDER wins
    best = min(results, key=lambda r: (round(r[0], 6), order.index(r[2])))
    if best[0] > 0.25:                      # mostly unmapped bytes: not a BASIC image
        return None, None
    group, model = best[2], best[3]
    if group in FAMILY15:
        # PC-1600 stores line targets as 1F hi lo 00; the PC-1500 never does
        has1f = re.search(rb"\x1f..\x00", data) is not None
        group, model = ("PC1600", "1600") if has1f else ("PC1500", "1500")
    return group, model


def cmd_detokenize(args):
    if args.model is None:
        gdata = Path(args.input).read_bytes()
        g, m = guess_group(gdata)
        if g is None:
            print("Could not detect the pocket model from the file; "
                  "please give --model.", file=sys.stderr)
            return 1
        args.model = m
        same = {"OLD": "PC-1245...1255", "NEW3": "PC-1403/1425/1440/1445/1460 and similar",
                "EXT": "PC-1280/1360/1470/1475 (and E/G-series programs that use only shared keywords)",
                "E": "PC-E500/E550/E650 and similar", "G": "PC-E200/E220/G8xx",
                "PC1500": "PC-1500", "PC1600": "PC-1600"}[g]
        print(f"No --model given: detected the {g} family ({same}); decoding as PC-{m}. "
              "Use --model if the listing looks wrong.", file=sys.stderr)
    group, det_ext, _tok_ext = resolve_model(args.model)
    if group in FAMILY15:
        return cmd_detokenize15(args, group)
    if group in FAMILYOLD:
        return cmd_detokenize_old(args, group)
    use_ext = det_ext if args.ext is None else args.ext

    data = Path(args.input).read_bytes()
    records, start = read_image(data) if args.offset is None else \
        (parse_from(data, args.offset)[0], args.offset)
    if not records:
        print("No BASIC lines found.", file=sys.stderr)
        return 1
    # second, tolerant pass from the detected start: keeps lines after a damaged one
    t_records, warns, end_off = parse_tolerant(data, start)
    if len(t_records) >= len(records):
        records = t_records
    for w in warns:
        print("warning:", w, file=sys.stderr)
    if end_off < len(data) and data[end_off:end_off + 1] != bytes([EOP]):
        print(f"warning: {len(data) - end_off} byte(s) from offset {end_off} could not be "
              "read as lines", file=sys.stderr)
    names = fe_names(group, _MODEL[0], use_ext, True) if group in FAMILYFE else None

    def jump(addr, data=data, start=start):
        pos = addr - 52 + start                 # E series: 52-byte file header
        if 0 <= pos and pos + 2 <= len(data):
            return (data[pos] << 8) | data[pos + 1]
        return None

    lines, all_unknown, family_used, bad_len = [], set(), set(), []
    for line_no, declared, body, length_ok in records:
        try:
            if names is not None:
                text, used, unknown = detokenize_body_fe(body, names, group, jump)
            else:
                text, used, unknown = detokenize_body(body, use_ext, group)
        except Exception as exc:                 # keep going: the line can be fixed by hand
            text, used, unknown = "<" + body.hex() + f"> REM! {exc}", set(), set()
        if text.strip():                         # omit blank lines
            lines.append(f"{line_no} {text}")
        all_unknown |= unknown
        family_used |= {u for u in used if isinstance(u, int) and u in FAMILY_ONLY}
        if not length_ok:
            bad_len.append((line_no, declared, len(body) + 1))

    listing = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(listing, encoding="utf-8")
    else:
        sys.stdout.write(listing)

    log = sys.stderr
    print(f"Detokenized {len(records)} BASIC lines.", file=log)
    print("Unknown/non-mapped bytes:",
          " ".join(f"{b:02X}" for b in sorted(all_unknown)) or "none", file=log)
    if family_used:
        print("Tokens that may not exist on a plain PC-1403:",
              " ".join(f"{b:02X}={TOKENS[b]}" for b in sorted(family_used)), file=log)
    if bad_len:
        print("Lines whose length byte does not match (possible file damage):",
              " ".join(f"{n}(declared {d}, actual {a})" for n, d, a in bad_len), file=log)
    return 0


def cmd_detokenize_old(args, group="OLD"):
    data = Path(args.input).read_bytes()
    if args.tape:
        data = deblock_tape(data)
    records, _start = read_image_old(data, args.offset)
    if not records:
        print("No BASIC lines found (expected E0..E9 line headers; for a tape/Transfile "
              "stream try --tape).", file=sys.stderr)
        return 1
    lines, all_unknown, foreign = [], set(), set()
    for line_no, _decl, body, _ok in records:
        try:
            text, used, unknown = detokenize_body_old(body)
        except Exception as exc:
            text, used, unknown = "<" + body.hex() + f"> {exc}", set(), set()
        if text.strip():                         # omit blank lines
            lines.append(f"{line_no} {text}")
        all_unknown |= unknown
        if group == "P1211":
            foreign |= {OLD_TOKENS[b] for b in used if OLD_TOKENS[b] not in P1211_NAMES}
    listing = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(listing, encoding="utf-8")
    else:
        sys.stdout.write(listing)
    print(f"Detokenized {len(records)} BASIC lines.", file=sys.stderr)
    print("Unknown/non-mapped bytes:",
          " ".join(f"{b:02X}" for b in sorted(all_unknown)) or "none", file=sys.stderr)
    if foreign:
        print("warning: keywords a PC-1210/1211/1212 does not have: "
              + " ".join(sorted(foreign)), file=sys.stderr)
    if records[-1][3] is False:
        print("warning: the last line has no 00 terminator (truncated file?)", file=sys.stderr)
    return 0


def cmd_detokenize15(args, group):
    reg = registry_for(group)
    is1600 = group == "PC1600"
    data = Path(args.input).read_bytes()
    records, _start = read_image15(data, args.offset)
    if not [r for r in records if r is not None]:
        print("No BASIC lines found.", file=sys.stderr)
        return 1
    lines, all_unknown, bad_len, count = [], set(), [], 0
    for rec in records:
        if rec is None:
            lines.append("#SEGMENT")
            continue
        line_no, declared, body, ok = rec
        text, _used, unknown = detokenize_body15(body, reg, is1600)
        if text.strip():                         # omit blank lines
            lines.append(f"{line_no} {text}")
        all_unknown |= unknown
        count += 1
        if not ok:
            bad_len.append((line_no, declared, len(body) + 1))
    listing = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(listing, encoding="utf-8")
    else:
        sys.stdout.write(listing)
    log = sys.stderr
    print(f"Detokenized {count} BASIC lines.", file=log)
    print("Unknown/non-mapped bytes:",
          " ".join(f"{b:02X}" for b in sorted(all_unknown)) or "none", file=log)
    if bad_len:
        print("Lines whose length byte does not match (possible file damage):",
              " ".join(f"{n}(declared {d}, actual {a})" for n, d, a in bad_len), file=log)
    return 0


def cmd_tokenize(args):
    group, _det_ext, tok_ext = resolve_model(args.model)
    use_ext = tok_ext if args.ext is None else args.ext
    fam15 = group in FAMILY15

    header = b""
    if args.header_hex and args.header_from:
        raise SystemExit("use either --header-hex or --header-from, not both")
    if args.header_hex:
        try:
            header = bytes.fromhex(args.header_hex)
        except ValueError:
            raise SystemExit("--header-hex must be hexadecimal, e.g. 7000000000000000")
    elif args.header_from:
        ref = Path(args.header_from).read_bytes()
        start = (read_image15(ref, args.offset)[1] if fam15 else
                 read_image_old(ref, args.offset)[1] if group in FAMILYOLD else
                 read_image(ref)[1])
        header = ref[:start]

    text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    if args.endmark and args.no_endmark:
        raise SystemExit("use either --endmark or --no-endmark, not both")
    # default: FF for the PC-1403 family, none for PC-1500/1600 (as in Pocket Tools)
    endmark = True if args.endmark else False if args.no_endmark else \
        (not fam15 and group not in FAMILYOLD)

    try:
        if group in FAMILYOLD:
            records = tokenize_listing_old(text, build_keywords_old(bool(use_ext), group),
                                           not args.rem_tokenize)
            lines = len(records)
            image = build_image_old(records, header, endmark)
        elif fam15:
            segments = tokenize_listing15(text, registry_for(group), group == "PC1600")
            lines = sum(len(sg) for sg in segments)
            image = build_image15(segments, header, endmark)
        else:
            if group in FAMILYFE:
                records = tokenize_listing_fe(text, fe_keywords(group, _MODEL[0], bool(use_ext)),
                                              group)
            else:
                records = tokenize_listing(text, build_keywords(use_ext, group),
                                           not args.rem_tokenize)
            lines = len(records)
            image = build_image(records, header, endmark) if records else b""
    except ValueError as e:
        raise SystemExit(f"error: {e}")
    if not lines:
        raise SystemExit("error: no BASIC lines found in the input")

    Path(args.output).write_bytes(image)
    print(f"Tokenized {lines} lines -> {len(image)} bytes "
          f"(header {len(header)} bytes, end marker {'yes' if endmark else 'no'}).",
          file=sys.stderr)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Sharp pocket computer BASIC tokenizer / detokenizer",
        usage="sharp_basic_v2.py det [--model MODEL] input [output]  |  sharp_basic_v2.py tok --model MODEL input output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("det", help="binary image -> BASIC text (output optional: prints to screen)")
    d.add_argument("--model", default=None,
                   help="pocket model, e.g. 1403, 1251, 1500, E500 (optional: detected from the file)")
    d.add_argument("input")
    d.add_argument("output", nargs="?")
    d.set_defaults(func=cmd_detokenize)

    t = sub.add_parser("tok", help="BASIC text -> binary image")
    t.add_argument("--model", default="1403", help="pocket model, e.g. 1403, 1251, 1500, E500 (default 1403)")
    t.add_argument("input")
    t.add_argument("output")
    t.set_defaults(func=cmd_tokenize)

    args = ap.parse_args(argv[1:])
    # fixed defaults for everything that used to be an option
    args.ext = None                # keyword set chosen by the model
    args.offset = None             # start of the program found automatically
    args.tape = False
    args.header_hex = args.header_from = None
    args.endmark = args.no_endmark = False     # end marker as usual for the model
    args.rem_tokenize = False                  # text after REM stays raw
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
