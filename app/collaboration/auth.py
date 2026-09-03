"""Reglas pequeñas de identidad para el espacio compartido de la empresa."""


def require_allowed_email(email: str | None, allowed_domain: str) -> str:
    """Normaliza correo Workspace y rechaza identidades externas al piloto."""
    normalized = (email or "").strip().casefold()
    domain = allowed_domain.strip().casefold().lstrip("@")
    if not normalized or not domain or not normalized.endswith("@" + domain):
        raise PermissionError("Esta cuenta no pertenece al dominio autorizado")
    return normalized
