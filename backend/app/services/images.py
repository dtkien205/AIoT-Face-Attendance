"""Validate uploaded image format before OpenCV/dlib decode."""
import io

from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def validate_image(body: bytes) -> None:
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Image is empty or larger than 5 MiB")
    try:
        with Image.open(io.BytesIO(body)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Only JPEG and PNG images are accepted")
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or oversized image") from exc
