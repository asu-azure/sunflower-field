import openpyxl

SKIP_SPEAKERS = {
    "Title/Cover Text",
    "Author Credit",
    "Author Credit (Social)",
    "Copyright",
    "Legal Notice",
    "Content Warning",
    "Subtitle",
    "Time",  # keep Time — this is actually a character name (narrator)
}

# These are truly non-dialogue metadata speaker labels to skip
METADATA_SPEAKERS = {
    "Title/Cover Text",
    "Author Credit",
    "Author Credit (Social)",
    "Copyright",
    "Legal Notice",
    "Content Warning",
    "Subtitle",
}


def load_manga_sheet(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["manga_translation_master_FINAL"]

    rows = []
    header_skipped = False
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not header_skipped:
            header_skipped = True
            continue
        if not any(row):
            continue

        page, panel, speaker, th, en, jp = (row[i] if i < len(row) else None for i in range(6))
        speaker_str = str(speaker).strip() if speaker else ""

        if speaker_str in METADATA_SPEAKERS:
            continue
        th_str = str(th).strip() if th else ""
        en_str = str(en).strip() if en else ""
        jp_str = str(jp).strip() if jp else ""
        if not th_str and not en_str:
            continue

        rows.append({
            "row_idx": row_idx,
            "page": str(page).strip() if page else "",
            "panel": str(panel).strip() if panel else "",
            "speaker": speaker_str,
            "th": th_str,
            "en": en_str,
            "jp": jp_str,
        })

    wb.close()
    return rows


def load_novel_sheet(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["novel_translation_master_FINAL"]

    rows = []
    header_skipped = False
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if not header_skipped:
            header_skipped = True
            continue
        if not any(row):
            continue

        para_num, th, en, jp = (row[i] if i < len(row) else None for i in range(4))
        th_str = str(th).strip() if th else ""
        en_str = str(en).strip() if en else ""
        jp_str = str(jp).strip() if jp else ""

        if not th_str or th_str == ".":
            continue

        rows.append({
            "row_idx": row_idx,
            "para_num": str(para_num).strip() if para_num else "",
            "th": th_str,
            "en": en_str,
            "jp": jp_str,
        })

    wb.close()
    return rows
