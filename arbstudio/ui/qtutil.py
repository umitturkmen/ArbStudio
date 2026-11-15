"""Qt ile ilgili küçük yardımcılar."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Type, TypeVar

from PySide6.QtWidgets import QComboBox

E = TypeVar("E", bound=Enum)


def combo_enum(box: QComboBox, enum_cls: Type[E], default: Optional[E] = None) -> Optional[E]:
    """`QComboBox` userData'sındaki değeri enum üyesine çevirir.

    Neden gerekli: `str` tabanlı enum'lar (`class Rule(str, Enum)`) userData'ya
    konduğunda Qt onları düz `str`'e dönüştürür. Geri okunan değer artık enum
    olmadığı için `is` karşılaştırmaları sessizce yanlış sonuç verir ve
    `.value` erişimi AttributeError fırlatır. Bu yüzden okuma tarafında her
    zaman buradan geçilir.
    """
    data = box.currentData()
    if data is None:
        return default
    if isinstance(data, enum_cls):
        return data
    try:
        return enum_cls(data)
    except ValueError:
        return default
