from __future__ import annotations

import asyncio

from spendinggovua_api.batch_export import export_form2_html_archive


if __name__ == "__main__":
    asyncio.run(export_form2_html_archive())
