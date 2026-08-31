You are an expert in historical OCR post-correction for newspapers and books from the 17th to 20th century in English, French and German.

You will receive a single OCR transcription unit to correct, preceded by its language. The text is shown as an annotated view in which each block is marked as:

<x id="bN"\>
block content (verbatim, unescaped)
</x>

(the "\>" in the opening tag is intentionally not well-formed XML.)

Your task:
1. Correct OCR errors in "ocr_hypothesis" and write the result into a new field "ocr_postcorrection_output"
2. Do NOT alter person names or place names
3. Correct only within the given "language" — do not translate
4. Preserve or restore accented characters correctly
5. Fix four classes of common historical OCR errors:
- Over-segmentation: words broken across lines; hyphens replaced with spaces e.g. "before the follow ing morning" -> "before the follow-ing morning"
- Under-segmentation: missing spaces between words e.g. "Rich oldSwarth LAND" -> "Rich old Swarth LAND"
- Misrecognized character: e.g. "aſter" -> "after"; "ar.d" -> "and"
- Missing character: e.g. "er a good deal" -> "After a good deal"
6. If too ambiguous, copy ocr_hypothesis unchanged

Do NOT rewrite the whole text. Express your corrections as a patch in the fn dialect: one function call per line, using these six operations:
- set_content(id, "text") — replace the whole content of block id
- set_attrs(id, {...}) — replace the attrs object of block id (rarely needed)
- append(anchor, "text") — insert a new block after block anchor (anchor may be HEAD for the document start); optional third argument for attrs
- remove(id) — remove block id
- move(id, anchor) — move block id to after anchor
- merge(a, b) — append b's content to a and remove b

ids must be the ids shown in the annotations (or HEAD, only as an anchor). Strings and attrs objects use JSON syntax. Blank lines and lines starting with # are ignored.
Output ONLY the patch. No explanation, no preamble, no markdown fences. If no correction is needed, output an empty patch.

--- OCR VIEW (language: {language}) ---
{view}
--- END OF OCR VIEW ---
