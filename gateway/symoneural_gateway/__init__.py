# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symoneural_gateway — the /v1 Messages-dialect gateway on 127.0.0.1:9001.

Four modules, one process:

    models.py   the three Symon model cards and the family-tier field the client needs
    worker.py   the httpx client to the chat unit; SYM_CHAT_URL is the only engine binding
    dialect.py  the /v1 router: /v1/models, /v1/messages, /v1/messages/count_tokens
    gateway.py  the FastAPI app, the credential check, and main()

Run it with `symoneural-gateway` (console script) or `python -m symoneural_gateway.gateway`.
Configuration is environment only; see config/symoneural-learn.env.example.
"""

__version__ = "1.0.0"
