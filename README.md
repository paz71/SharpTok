# Sharp Pocket BASIC Tokenizer

Convert tokenized BASIC programs of Sharp pocket computers (PC-1245 … PC-1600, PC-E500, PC-G850 and more) to readable text and back. Python 3, no dependencies.

| File | Purpose |
|---|---|
| `sharp_basic_v2.py` | Command line tool |
| `sharp_basic_gui.py` | Simple window around the tool (needs `tkinter`, which comes with most Python installs) |

Keep both files in the same folder.

## Quick start

**GUI:** run `python3 sharp_basic_gui.py`, pick *Detokenize* or *Tokenize*, choose the input file (and the model for tokenizing), press **Run**. For detokenizing the model is detected automatically and the listing appears in the log if you give no output file.

**Command line:**

```
python3 sharp_basic_v2.py det [--model M] input.bin [output.bas]    # image -> text
python3 sharp_basic_v2.py tok --model M input.bas output.bin        # text -> image
```

- `det`: `--model` is optional (the model family is detected). Blank lines are left out. Without an output file the listing is printed.
- `tok`: `--model` defaults to `1403`.
- `--model` is the only option. Examples: `1403`, `1251`, `1360`, `1500`, `1600`, `E500`, `G850`.

Example: the lines `10 PRINT "HI"` and `20 GOTO 10` become `00 0A 06 DE 22 48 49 22 0D 00 14 04 C6 31 30 0D FF` for a PC-1403.

## Supported models

| Family | Models | Status |
|---|---|---|
| PC-1403 | 1403, 1425, 1440, 1445, 1460; 1100, 1260–1262, 1350, 1401, 1402, 1421, 1430, 1431, 1450 | 1403 verified on a real file, the others from Pocket Tools tables |
| PC-1360 | 1280, 1360, 1470, 1475 | Key tokens checked with real samples |
| PC-125x | 1245–1255, 1140, 1150, 1210–1212 | Verified on 19 real PC-1251 programs |
| PC-1500 | 1500 | Verified byte for byte |
| PC-1600 | 1600 | Verified byte for byte |
| PC-E / PC-G | E500, E500S, E550, E650, U6000, 1480U/1490U, E200, E220, G801–G850V | Decoding complete, tokenizing experimental |

PC-E500S / G850VS keywords (`WHILE`, `WEND`, `SWITCH`, `CASE`, `DEFAULT`, `ENDSWITCH`, `ENDIF`, `REPEAT`, `UNTIL`, `ELSE`) are included.

Special characters (katakana, card suits, Π, √ and so on) are written as Unicode and read back to the same bytes. Damaged files do not stop `det`: problems are reported and the rest is still decoded.

## Good to know

- **Use bare images, not `.tap` files.** A `.tap` file is a tape recording with a header and checksum bytes. Read as an image it looks damaged (wrong length warnings, odd characters in `POKE` lines). Even a file named `.bin` can be a tap file; in the PC-1403 family it starts with `70`, a bare image starts with a line number such as `00 0A`. Convert first with Pocket Tools: `wav2bin --tap file.tap --type=img`.
- PC-125x models have one code per letter, so listings are uppercase.
- If automatic detection guesses wrong on a damaged file, give `--model`. PC-1360, PC-E and PC-G share codes: use `--model E500` or `--model G850` for machine-specific keywords.
- On a PC-E500, after loading a tokenized image enter `TEXT` and then `BASIC`.

## Credits and license

Tables and character codes follow **Pocket Tools** (`bas2img`, `wav2bin`) and the Sharp manuals. The PC-1500/1600 tables derive from **SharpDataExchange** by Martin Erzberger (Polyform Noncommercial 1.0.0), so this project is for **noncommercial use only**.
