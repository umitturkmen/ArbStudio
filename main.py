"""Paketten bağımsız giriş noktası — PyInstaller bu dosyayı kullanır.

`arbstudio/__main__.py` paket-göreli import kullandığı için doğrudan betik
olarak çalıştırılamaz; buradan paket olarak içe aktarılır.
"""

from __future__ import annotations

import sys

from arbstudio.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
