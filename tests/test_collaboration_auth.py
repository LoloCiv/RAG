"""El dominio permitido evita que un link privado se vuelva acceso al espacio."""

import pytest

from app.collaboration.auth import require_allowed_email


def test_allowed_workspace_email_is_normalized():
    assert require_allowed_email("Sofia@AuroraEventos.com", "auroraeventos.com") == "sofia@auroraeventos.com"


def test_external_email_is_rejected():
    with pytest.raises(PermissionError):
        require_allowed_email("proveedor@gmail.com", "auroraeventos.com")
