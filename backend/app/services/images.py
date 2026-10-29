"""Validate dimensions before OpenCV/dlib decode; reject decompression bombs."""
import io
import warnings

from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 4_000_000


def validate_image(body: bytes) -> None:
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or larger than 5 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                if image.format not in {"JPEG", "PNG"}:
                    raise ValueError("Only JPEG and PNG images are accepted")
                width, height = image.size
                if min(width, height) < 64 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions must be at least 64×64 and at most 4 megapixels")
                image.verify()
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid or oversized image") from exc
