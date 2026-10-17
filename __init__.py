# -*- coding: utf-8 -*-
"""Addon ``printflow_gestion_inventario`` (Gestión de Inventario).

Extraído de ``x_product_dimensional_pricing``: contiene el diagnóstico/diagrama
(Niveles 2/3) y el tablero de Salud de Inventario (bandeja, Productos,
Pendientes, Mantenimiento). Depende del addon principal (solo lectura de su
cerebro de reglas: health engine / stock.health / stock.remedy).
"""

from . import models
from . import wizard
