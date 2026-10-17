# -*- coding: utf-8 -*-
"""Chequeos del diagnóstico de producto (PrintFlow).

Cada archivo registra UN chequeo sobre el motor ``printflow.product.check.mixin``.
Para agregar uno nuevo basta con crear el archivo y añadir su import aquí; no se
toca ningún chequeo existente ni el motor.
"""

from . import check_inventory
from . import check_kit
from . import check_bom_duplicated
from . import check_bom_archive_blocked
from . import check_orderpoint
from . import check_uom
from . import check_routing
from . import check_pending_sales
from . import check_manufacturing
from . import check_record_state
# FASE 4: flujo unificado (consume printflow.product.flow.diagnostic).
from . import check_flow
