"""Des archives Strava inventées (AN1-3), rangées comme les vraies :
``raw/strava/<export>/acquisition.json`` et ``raw/strava/<export>/export_1.zip``. Aucune
donnée réelle (règle 1) : l'en-tête d'``activities.csv`` est une forme (des noms de
colonnes), recopiée ici, dans sa propre copie, depuis le paquet du brief d'AN1-3 — le
test ne la prend pas du module testé ; les autres valeurs sont inventées.

Les membres personnels (``profile.csv``, ``messaging.json``, ``media/…``) portent le bit
de chiffrement, dans leur en-tête local et dans le répertoire central : ``ZipFile.read``
lève ``RuntimeError`` sur eux. Une lecture qui en ouvrirait un se verrait.
"""

from __future__ import annotations

import csv
import io
import json
import struct
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

STRAVA_HEADER: Final[tuple[str, ...]] = (
    "Activity ID",
    "Activity Date",
    "Activity Name",
    "Activity Type",
    "Activity Description",
    "Elapsed Time",
    "Distance",
    "Max Heart Rate",
    "Relative Effort",
    "Commute",
    "Activity Private Note",
    "Activity Gear",
    "Filename",
    "Athlete Weight",
    "Bike Weight",
    "Elapsed Time",
    "Moving Time",
    "Distance",
    "Max Speed",
    "Average Speed",
    "Elevation Gain",
    "Elevation Loss",
    "Elevation Low",
    "Elevation High",
    "Max Grade",
    "Average Grade",
    "Average Positive Grade",
    "Average Negative Grade",
    "Max Cadence",
    "Average Cadence",
    "Max Heart Rate",
    "Average Heart Rate",
    "Max Watts",
    "Average Watts",
    "Calories",
    "Max Temperature",
    "Average Temperature",
    "Relative Effort",
    "Total Work",
    "Number of Runs",
    "Uphill Time",
    "Downhill Time",
    "Other Time",
    "Perceived Exertion",
    "Type",
    "Start Time",
    "Weighted Average Power",
    "Power Count",
    "Prefer Perceived Exertion",
    "Perceived Relative Effort",
    "Commute",
    "Total Weight Lifted",
    "From Upload",
    "Grade Adjusted Distance",
    "Weather Observation Time",
    "Weather Condition",
    "Weather Temperature",
    "Apparent Temperature",
    "Dewpoint",
    "Humidity",
    "Weather Pressure",
    "Wind Speed",
    "Wind Gust",
    "Wind Bearing",
    "Precipitation Intensity",
    "Sunrise Time",
    "Sunset Time",
    "Moon Phase",
    "Bike",
    "Gear",
    "Precipitation Probability",
    "Precipitation Type",
    "Cloud Cover",
    "Weather Visibility",
    "UV Index",
    "Weather Ozone",
    "Jump Count",
    "Total Grit",
    "Average Flow",
    "Flagged",
    "Average Elapsed Speed",
    "Dirt Distance",
    "Newly Explored Distance",
    "Newly Explored Dirt Distance",
    "Activity Count",
    "Total Steps",
    "Carbon Saved",
    "Pool Length",
    "Training Load",
    "Intensity",
    "Average Grade Adjusted Pace",
    "Timer Time",
    "Total Cycles",
    "Recovery",
    "With Pet",
    "Competition",
    "Long Run",
    "For a Cause",
    "With Kid",
    "Downhill Distance",
    "Total Sets",
    "Total Reps",
    "Media",
    "Tag",
)
"""La copie des tests de l'en-tête attendu (104 noms, cinq en double)."""

READ_RANK: Final[Mapping[str, int]] = {
    "Elapsed Time": 15,
    "Distance": 17,
    "Max Heart Rate": 30,
}
"""Le rang que l'ingestion lit, pour les noms en double qu'elle lit : une clé de ce
nom remplit ce rang ; la première occurrence reçoit le texte plausible."""

PLAUSIBLE: Final[Mapping[int, str]] = {
    2: "Sortie",
    4: "Ligne 1\nLigne 2",
    5: "3600",
    6: "10.5",
    7: "170",
    8: "42",
    9: "false",
    10: "note inventée",
    11: "chaussures inventées",
    44: "",
}
"""Des textes plausibles et inventés pour des colonnes que l'ingestion ne lit pas (la
première ``Distance`` en km)."""

PERSONAL_MEMBERS: Final = ("profile.csv", "messaging.json", "media/photo_1.jpg")
"""Les membres personnels, illisibles par ``zipfile`` (bit de chiffrement posé)."""

_ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)


def _rank(name: str) -> int:
    """Le rang d'une colonne nommée : le rang lu pour un nom en double qu'elle lit,
    sinon la première occurrence."""
    if name in READ_RANK:
        return READ_RANK[name]
    return STRAVA_HEADER.index(name)


def _line(row: Mapping[str, str] | Sequence[str]) -> list[str]:
    if not isinstance(row, Mapping):
        return list(row)
    fields = [PLAUSIBLE.get(rank, "") for rank in range(len(STRAVA_HEADER))]
    for name, value in row.items():
        fields[_rank(name)] = value
    return fields


def _info(name: str, compression: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
    info.compress_type = compression
    info.create_system = 0
    info.external_attr = 0
    return info


def mark_encrypted(data: bytes, names: Sequence[str]) -> bytes:
    """Pose le bit de chiffrement (bit 0 des drapeaux) des membres ``names``, dans leur
    en-tête local et dans le répertoire central ; les données ne changent pas."""
    out = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        offsets = {
            info.filename: info.header_offset
            for info in archive.infolist()
            if info.filename in names
        }
    for offset in offsets.values():
        out[offset + 6] |= 0x01
    end = out.rfind(b"PK\x05\x06")
    position = struct.unpack("<I", out[end + 16 : end + 20])[0]
    while out[position : position + 4] == b"PK\x01\x02":
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", out[position + 28 : position + 34]
        )
        name = out[position + 46 : position + 46 + name_len].decode("utf-8")
        if name in offsets:
            out[position + 8] |= 0x01
        position += 46 + name_len + extra_len + comment_len
    return bytes(out)


def write_strava_export(
    data_dir: Path,
    name: str,
    *,
    retrieved_at: str,
    timezone: str | None = None,
    rows: Sequence[Mapping[str, str] | Sequence[str]],
    members: Mapping[str, bytes],
    personal: bool = True,
    header: Sequence[str] | None = None,
) -> Path:
    """Écrit ``data_dir/raw/strava/<name>/`` : ``acquisition.json`` (``retrieved_at``,
    et ``timezone`` s'il est donné) et ``export_1.zip`` — ``activities.csv`` (l'en-tête
    ``header``, par défaut ``STRAVA_HEADER``, puis une ligne par ``rows`` : un
    ``Mapping`` indexé par nom de colonne, les autres colonnes plausibles ; une
    ``Sequence`` écrite telle quelle), les ``members`` (``activities/<nom>`` → octets,
    stockés), et, si ``personal``, les membres personnels illisibles. Métadonnées fixes.
    Rend le dossier de l'export."""
    folder = data_dir / "raw" / "strava" / name
    folder.mkdir(parents=True)
    acquisition: dict[str, str] = {"retrieved_at": retrieved_at}
    if timezone is not None:
        acquisition["timezone"] = timezone
    (folder / "acquisition.json").write_text(json.dumps(acquisition), encoding="utf-8")
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(STRAVA_HEADER if header is None else header)
    for row in rows:
        writer.writerow(_line(row))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            _info("activities.csv", zipfile.ZIP_DEFLATED),
            text.getvalue().encode("utf-8"),
        )
        for member, data in members.items():
            archive.writestr(_info(member, zipfile.ZIP_STORED), data)
        if personal:
            for member in PERSONAL_MEMBERS:
                archive.writestr(
                    _info(member, zipfile.ZIP_DEFLATED), b"donnee personnelle inventee"
                )
    data = buffer.getvalue()
    if personal:
        data = mark_encrypted(data, PERSONAL_MEMBERS)
    (folder / "export_1.zip").write_bytes(data)
    return folder
