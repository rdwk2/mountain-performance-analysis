"""Un petit écrivain FIT en Python pur, pour les tests du lecteur FIT (``0011``).

fitdecode ne sait pas écrire : les tests décodent des FIT synthétiques, minuscules,
écrits ici (règle 1 : aucun FIT réel dans le dépôt). L'écrivain connaît l'en-tête de
14 octets, les messages de définition (avec champs de développeur), les messages de
données à en-tête normal ou à horodatage compressé, et le CRC du fichier. Il écrit les
valeurs **brutes** (semicercles, altitude ``(m + 500) × 5``…), sans les profils : ce
sont les tests qui disent quelle valeur décodée ils attendent.

Spécification : FIT Protocol, document du SDK de Garmin (structure du fichier, en-têtes
d'enregistrement, CRC) ; aucun code du SDK n'est repris.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Types de base FIT : (numéro, format struct, taille, valeur invalide).
ENUM = (0x00, "B", 1, 0xFF)
SINT8 = (0x01, "b", 1, 0x7F)
UINT8 = (0x02, "B", 1, 0xFF)
SINT16 = (0x83, "h", 2, 0x7FFF)
UINT16 = (0x84, "H", 2, 0xFFFF)
SINT32 = (0x85, "i", 4, 0x7FFFFFFF)
UINT32 = (0x86, "I", 4, 0xFFFFFFFF)
UINT32Z = (0x8C, "I", 4, 0x00000000)
STRING = (0x07, "s", 0, 0x00)
BYTE = (0x0D, "s", 0, 0xFF)

BaseType = tuple[int, str, int, int]

_CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)  # fmt: skip


def fit_crc(data: bytes, crc: int = 0) -> int:
    """Le CRC-16 du protocole FIT."""
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


@dataclass(frozen=True)
class FieldDef:
    """Un champ d'une définition : son numéro, son type de base, et sa taille (pour un
    texte ou un tableau d'octets ; sinon celle du type)."""

    number: int
    base_type: BaseType
    size: int = 0

    @property
    def byte_size(self) -> int:
        return self.size or self.base_type[2]


@dataclass(frozen=True)
class DevFieldDef:
    """Un champ de développeur d'une définition."""

    number: int
    size: int
    developer_index: int


@dataclass
class FitWriter:
    """Accumule les messages d'un fichier FIT, puis rend ses octets."""

    profile_version: int = 2132
    _body: bytearray = field(default_factory=bytearray)
    _defs: dict[int, tuple[tuple[FieldDef, ...], tuple[DevFieldDef, ...]]] = field(
        default_factory=dict
    )

    def define(
        self,
        local: int,
        global_number: int,
        fields: tuple[FieldDef, ...],
        dev_fields: tuple[DevFieldDef, ...] = (),
    ) -> None:
        """Un message de définition, petit-boutiste, pour le type local ``local``."""
        header = 0x40 | (0x20 if dev_fields else 0) | (local & 0x0F)
        out = bytearray(struct.pack("<BBBHB", header, 0, 0, global_number, len(fields)))
        for f in fields:
            out += struct.pack("<BBB", f.number, f.byte_size, f.base_type[0])
        if dev_fields:
            out += struct.pack("<B", len(dev_fields))
            for d in dev_fields:
                out += struct.pack("<BBB", d.number, d.size, d.developer_index)
        self._body += out
        self._defs[local] = (fields, dev_fields)

    def data(
        self,
        local: int,
        values: tuple[int | bytes | str | None, ...],
        dev_values: tuple[bytes, ...] = (),
        *,
        time_offset: int | None = None,
    ) -> None:
        """Un message de données du type local ``local`` ; ``None`` écrit la valeur
        invalide du type. ``time_offset`` (0 à 31) écrit un en-tête à horodatage
        compressé (type local 0 à 3)."""
        fields, dev_fields = self._defs[local]
        if len(values) != len(fields) or len(dev_values) != len(dev_fields):
            raise ValueError("autant de valeurs que de champs définis")
        if time_offset is None:
            header = local & 0x0F
        else:
            if not 0 <= local <= 3 or not 0 <= time_offset <= 31:
                raise ValueError("en-tête compressé : type local 0-3, décalage 0-31")
            header = 0x80 | (local << 5) | time_offset
        out = bytearray([header])
        for f, value in zip(fields, values, strict=True):
            out += _encode(f, value)
        for d, raw in zip(dev_fields, dev_values, strict=True):
            if len(raw) != d.size:
                raise ValueError("taille d'un champ de développeur")
            out += raw
        self._body += out

    def to_bytes(self, *, corrupt_crc: bool = False) -> bytes:
        """L'en-tête de 14 octets (avec son CRC), les messages, et le CRC du fichier ;
        ``corrupt_crc`` écrit un CRC de fichier faux."""
        head = struct.pack(
            "<BBHI4s", 14, 0x20, self.profile_version, len(self._body), b".FIT"
        )
        head += struct.pack("<H", fit_crc(head))
        content = head + bytes(self._body)
        crc = fit_crc(content) ^ (0x0001 if corrupt_crc else 0)
        return content + struct.pack("<H", crc)


def _encode(f: FieldDef, value: int | bytes | str | None) -> bytes:
    _, fmt, _, invalid = f.base_type
    if fmt == "s":
        width = f.byte_size
        if value is None:
            return bytes([invalid]) * width
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if not isinstance(raw, bytes) or len(raw) > width:
            raise ValueError("texte ou octets trop longs")
        return raw.ljust(width, b"\x00")
    if value is None:
        return struct.pack("<" + fmt, invalid)
    if not isinstance(value, int):
        raise ValueError("valeur entière attendue")
    return struct.pack("<" + fmt, value)
