from __future__ import annotations

from .config import get_settings, validate_production_settings
from .license_protocol import signing_material, trusted_public_keys


def main() -> int:
    settings = get_settings()
    validate_production_settings(settings)
    material = signing_material()
    trusted_public_keys()
    print(f"KeyDesk configuration preflight passed (kid={material.kid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
