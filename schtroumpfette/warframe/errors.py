"""Texte lisible d'une erreur de téléchargement, pour les logs."""
import aiohttp


def describe(error: Exception, timeout: aiohttp.ClientTimeout) -> str:
    """Délai dépassé → « pas de réponse en N s » (TimeoutError n'a pas de texte), erreur HTTP → « HTTP 503 »,
    autre erreur → nom de l'exception et son texte."""
    if isinstance(error, TimeoutError):
        return f"pas de réponse en {timeout.total:g} s"
    if isinstance(error, aiohttp.ClientResponseError):
        return f"HTTP {error.status}"
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__
