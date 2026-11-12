"""Préparation d'une capture pour /cephalon_build : réduction et encodage (Pillow, appel bloquant : dans un thread)."""
import base64
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from cephalon.config import IMAGE_MAX_EDGE, IMAGE_PNG_LIMIT

JPEG_QUALITY = 90  # assez pour garder lisibles les petits textes d'une capture


class ImageError(Exception):
    """Fichier qui n'est pas une image lisible."""


@dataclass
class PreparedImage:
    media_type: str      # image/png ou image/jpeg
    data: str            # base64, sans retour à la ligne
    original: tuple[int, int]
    size: tuple[int, int]
    bytes: int           # taille encodée (avant base64)

    def block(self) -> dict:
        """Bloc image de l'API Anthropic."""
        return {"type": "image", "source": {"type": "base64", "media_type": self.media_type, "data": self.data}}

    def summary(self) -> str:
        (width, height), (new_width, new_height) = self.original, self.size
        resized = "" if self.original == self.size else f" → {new_width}x{new_height}"
        return f"{width}x{height}{resized}, {self.media_type.split('/')[1].upper()} {self.bytes // 1024} Ko"


def prepare(data: bytes) -> PreparedImage:
    """Première image d'un fichier (GIF compris), réduite à IMAGE_MAX_EDGE px de côté, en PNG ou en JPEG si trop lourde."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            original = source.size
            image = source.convert("RGBA" if source.mode in ("RGBA", "LA", "P") else "RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ImageError(f"image illisible ({error})") from error
    if max(image.size) > IMAGE_MAX_EDGE:
        ratio = IMAGE_MAX_EDGE / max(image.size)
        image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    media_type = "image/png"
    if buffer.tell() > IMAGE_PNG_LIMIT:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
        media_type = "image/jpeg"
    encoded = buffer.getvalue()
    return PreparedImage(media_type=media_type, data=base64.standard_b64encode(encoded).decode("ascii"),
                         original=original, size=image.size, bytes=len(encoded))
