"""Reduce preview upload bytes while preserving original inputs for final/review."""
import hashlib
from pathlib import Path
import shlex

from PIL import Image, ImageOps


def prepare_inputs(request, out_dir):
    """Update only preview upload argv and provenance, never crop or overwrite.

    Final requests keep original photo/style/approved-preview files. Input
    resizing can reduce transfer and image input work; it is not a latency SLA.
    """
    if request.get('stage') != 'preview':
        return request
    argv = list(request['argv'])
    positions = [index + 1 for index, value in enumerate(argv) if value == '--image']
    if len(positions) != 2:
        raise ValueError('预览应包含人物照片和独立风格图两张输入')
    out_dir = Path(out_dir).resolve()
    mappings = []
    for number, position in enumerate(positions):
        source = Path(argv[position]).resolve()
        original_bytes = source.read_bytes()
        role = 'photo' if number == 0 else 'style'
        edge = 1024 if role == 'photo' else 512
        destination = source
        with Image.open(source) as raw:
            if getattr(raw, 'n_frames', 1) != 1:
                raise ValueError('预览输入需要单帧图片')
            source_size = list(raw.size)
            orientation = raw.getexif().get(274, 1)
            oriented = ImageOps.exif_transpose(raw)
            needs_resize = max(oriented.size) > edge
            should_encode = needs_resize or orientation not in (None, 1) or len(original_bytes) > 256 * 1024
            if should_encode:
                alpha = 'A' in oriented.getbands() or 'transparency' in oriented.info
                translucent = alpha and oriented.convert('RGBA').getchannel('A').getextrema()[0] < 255
                image = oriented.convert('RGBA' if translucent else 'RGB')
                image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                extension = '.png' if role == 'style' or translucent else '.jpg'
                out_dir.mkdir(parents=True, exist_ok=True)
                destination = out_dir / (role + extension)
                if destination.resolve() == source or destination.exists():
                    raise ValueError('上传副本已存在，不能覆盖原图或此前版本')
                with destination.open('xb') as stream:
                    if extension == '.jpg':
                        image.save(stream, format='JPEG', quality=90, subsampling=0)
                    else:
                        image.save(stream, format='PNG')
                # Reencoding an already-small source may not save bytes.
                # Keep that source unless resizing/EXIF normalization was needed.
                if not needs_resize and orientation in (None, 1) and destination.stat().st_size >= len(original_bytes):
                    destination.unlink()
                    destination = source
                    upload_size = list(oriented.size)
                else:
                    upload_size = list(image.size)
            else:
                upload_size = list(oriented.size)
        uploaded_bytes = original_bytes if destination == source else destination.read_bytes()
        mappings.append({
            'role': role, 'source': str(source), 'upload': str(destination),
            'source_size': source_size, 'upload_size': upload_size,
            'source_bytes': len(original_bytes), 'upload_bytes': len(uploaded_bytes),
            'source_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'upload_sha256': hashlib.sha256(uploaded_bytes).hexdigest(),
        })
        argv[position] = str(destination)
    request['argv'] = argv
    request['shell_command'] = shlex.join(argv)
    request['upload_inputs'] = mappings
    return request
