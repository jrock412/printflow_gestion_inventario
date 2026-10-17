# -*- coding: utf-8 -*-
"""CONTRATO base del patrón de fallas guiadas desde el diagrama (PrintFlow).

``AbstractModel`` SIN tabla (igual que ``printflow.flow.registry`` o
``printflow.flow.lots``): **NO** lleva fila en ``security/ir.model.access.csv``.
Define el CONTRATO que toda falla concreta implementa para que el diagrama de
flujo pueda guiar su corrección desde una superficie GENÉRICA
(``printflow.flow.failure.tray``).

Por qué existe
--------------
El "Solucionar" de un hallazgo debe dejar de ser un one-click ciego: el operador
ve qué está mal (una fila por evidencia) y decide. El patrón OOP separa:

* el **registry** (``printflow.flow.failure.registry``) resuelve código -> falla;
* cada **falla** (p. ej. ``printflow.flow.failure.lot.orphan``) sabe DETECTAR y
  EJECUTAR su corrección reutilizando el motor del addon principal (x);
* la **bandeja** (``printflow.flow.failure.tray``) es una superficie genérica que
  solo PINTA lo que la falla declara.

Contrato (métodos privados con docstring; se invocan SIEMPRE desde el registry o
la bandeja, NUNCA por convención ``getattr``)::

    code     = failure._pf_fault_code()
    obs      = failure._pf_fault_detect(host, ctx)   # NotImplementedError
    severity = failure._pf_fault_severity(ctx)
    summary  = failure._pf_fault_summary(ctx)
    steps    = failure._pf_fault_steps(ctx)
    rows     = failure._pf_fault_evidences(ctx)
    actions  = failure._pf_fault_actions(ctx)
    msg      = failure._pf_fault_execute(action_key, ctx)  # NotImplementedError
    tray     = failure._pf_fault_tray_model()

``ctx`` es un dict con al menos ``{'host', 'product', 'code', 'observation'}``.

Por defecto ``_pf_fault_detect`` y ``_pf_fault_execute`` lanzan
``NotImplementedError`` (obligan a la falla concreta a implementarlos); el resto
devuelve vacío/``warning``. No se usa ``getattr`` por convención.
"""

from odoo import api, models


class PrintflowFlowFailure(models.AbstractModel):
    """Contrato base de una falla guiada (sin tabla)."""

    _name = 'printflow.flow.failure'
    _description = 'Contrato base de falla guiada (PrintFlow)'

    # Modelo de la bandeja genérica que pinta la falla (superficie única).
    _PF_TRAY_MODEL = 'printflow.flow.failure.tray'

    @api.model
    def _pf_fault_code(self):
        """Código normalizado de la falla (clave del registry)."""
        return self._name

    @api.model
    def _pf_fault_detect(self, host, ctx=None):
        """Observa el ``host`` y devuelve la observación, o algo falsy si no aplica.

        Obligatorio en cada falla concreta: aquí lanza ``NotImplementedError``
        para que ninguna falla quede muda ante el diagrama.
        """
        raise NotImplementedError

    @api.model
    def _pf_fault_severity(self, ctx):
        """Severidad para el semáforo (``ok`` | ``warning`` | ``danger``)."""
        return 'warning'

    @api.model
    def _pf_fault_summary(self, ctx):
        """Resumen en palabras simples del hallazgo (encabezado de la bandeja)."""
        return ''

    @api.model
    def _pf_fault_steps(self, ctx):
        """Pasos guiados (lista de strings) de cómo resolver el hallazgo."""
        return []

    @api.model
    def _pf_fault_evidences(self, ctx):
        """Evidencias del hallazgo: UNA fila (dict) por ítem afectado."""
        return []

    @api.model
    def _pf_fault_actions(self, ctx):
        """Acciones guiadas por fila (``key``/``label``/``kind``/``enabled``/``primary``).

        ``kind`` ∈ ``execute`` (la ejecuta la falla vía ``_pf_fault_execute``),
        ``navigate`` (la resuelve la bandeja) o ``close`` (cierra la bandeja).
        """
        return []

    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """Ejecuta una acción con EFECTO (obligatorio en cada falla concreta)."""
        raise NotImplementedError

    @api.model
    def _pf_fault_tray_model(self):
        """Nombre del modelo de la bandeja que pinta la falla."""
        return self._PF_TRAY_MODEL
