"""Generates a text comparison report between two meeting minutes sources.

Compares what is officially posted on MyTownGovernment.org (minutes_url present)
against what is listed on the Hardwick town website (hardwick-ma.gov).
"""
from datetime import date

_KEY_DATE = 'date'
_KEY_MINUTES_URL = 'minutes_url'
_REPORT_TITLE = 'Hardwick Select Board Minutes — Source Comparison'
_DATE_COL_W = 12
_MTG_COL_W = 3
_TOWN_COL_W = 4
_TITLE_COL_W = 50
_DIVIDER_W = 72
_COL_HEADER = 'DATE          MTG  TOWN  TOWN TITLE'
_COL_DIVIDER = '-' * _DIVIDER_W
_YES = 'Y'


def _has_official_minutes(meeting: dict) -> bool:
    return bool(meeting.get(_KEY_MINUTES_URL))


def _label_by_date(records: list[dict]) -> dict:
    """Return a dict mapping date string to record for quick lookup."""
    return {
        rec[_KEY_DATE]: rec
        for rec in records
        if rec.get(_KEY_DATE)
    }


def _format_both_row(date_str: str, rec: dict) -> str:
    date_part = date_str.ljust(_DATE_COL_W)
    mtg_part = _YES.rjust(_MTG_COL_W)
    town_part = _YES.rjust(_TOWN_COL_W)
    town_title = rec.get('title', '')[:_TITLE_COL_W]
    return f'{date_part}  {mtg_part}  {town_part}  {town_title}'


def _format_only_row(date_str: str, mtg_flag: str, town_flag: str) -> str:
    date_part = date_str.ljust(_DATE_COL_W)
    mtg_part = mtg_flag.rjust(_MTG_COL_W)
    town_part = town_flag.rjust(_TOWN_COL_W)
    return f'{date_part}  {mtg_part}  {town_part}'


def _section_both(
    all_dates: list[str],
    mtg_set: set,
    town_set: set,
    town_by_date: dict,
) -> list[str]:
    lines = ['', 'MEETINGS ON BOTH SOURCES:', _COL_HEADER, _COL_DIVIDER]
    rows = [date_str for date_str in all_dates if date_str in mtg_set and date_str in town_set]
    if not rows:
        lines.append('  (none)')
        return lines
    for date_str in rows:
        lines.append(_format_both_row(date_str, town_by_date.get(date_str, {})))
    return lines


def _section_only(dates: list[str], heading: str, source_col: str) -> list[str]:
    lines = ['', f'{heading}:', _COL_HEADER, _COL_DIVIDER]
    if not dates:
        lines.append('  (none)')
        return lines
    mtg_flag = _YES if source_col == 'MTG' else ' '
    town_flag = _YES if source_col == 'TOWN' else ' '
    for date_str in dates:
        lines.append(_format_only_row(date_str, mtg_flag, town_flag))
    return lines


def _section_summary(n_both: int, n_mtg: int, n_town: int) -> list[str]:
    total = n_both + n_mtg + n_town
    fmt_both = str(n_both).rjust(4)
    fmt_mtg = str(n_mtg).rjust(4)
    fmt_town = str(n_town).rjust(4)
    fmt_total = str(total).rjust(4)
    return [
        '',
        'SUMMARY:',
        f'  On both sources:          {fmt_both}',
        f'  Only on MyTownGovernment: {fmt_mtg}',
        f'  Only on hardwick-ma.gov:  {fmt_town}',
        f'  Total:                    {fmt_total}',
    ]


def _build_comparison(meetings: list[dict], town_records: list[dict]) -> dict:
    """Return a dict with mtg_set, town_by_date, town_set, all_dates, only_mtg, only_town."""
    mtg_set = {
        mtg[_KEY_DATE]
        for mtg in meetings
        if mtg.get(_KEY_DATE) and _has_official_minutes(mtg)
    }
    town_by_date = _label_by_date(town_records)
    town_set = set(town_by_date)
    all_dates = sorted(mtg_set | town_set)
    only_mtg = sorted(mtg_set - town_set)
    only_town = sorted(town_set - mtg_set)
    return {
        'mtg_set': mtg_set,
        'town_by_date': town_by_date,
        'town_set': town_set,
        'all_dates': all_dates,
        'only_mtg': only_mtg,
        'only_town': only_town,
        'n_both': len(mtg_set & town_set),
    }


def compare_report(meetings: list[dict], town_records: list[dict]) -> str:
    """Return a formatted text comparison of minutes availability on both sites."""
    comp = _build_comparison(meetings, town_records)
    only_mtg = comp['only_mtg']
    only_town = comp['only_town']
    n_both = comp['n_both']
    today_str = date.today().isoformat()
    lines = [_REPORT_TITLE, f'Generated: {today_str}']
    lines += _section_both(
        comp['all_dates'], comp['mtg_set'], comp['town_set'], comp['town_by_date'],
    )
    lines += _section_only(only_mtg, 'Only on MyTownGovernment.org', 'MTG')
    lines += _section_only(only_town, 'Only on hardwick-ma.gov', 'TOWN')
    lines += _section_summary(n_both, len(only_mtg), len(only_town))
    return '\n'.join(lines)
