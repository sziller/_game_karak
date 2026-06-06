"""Example SHMC APP_ROUTER_INFO entry for Karak local-router integration.

Copy this into the SHMC server configuration; this file is documentation only.
"""

import os

APP_ROUTER_INFO_KARAK_EXAMPLE = {
    "karak": {
        "use": True,
        "prefix": "/karak",
        "module": "shmc_routers.KarakRouter_class",
        "class_name": "KarakRouter",
        "backend_kind": "local_router",
        "physical_location": "hetzner",
        "auth_required": False,
        "init": {
            "name": "karak",
            "alias": "Karak",
            "db_fullname": os.getenv("DB_FULLNAME_KARAK"),
            "db_style": os.getenv("DB_STYLE_KARAK"),
        },
    }
}
