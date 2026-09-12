from threading import Lock

# Serializing full-size image conversions prevents concurrent uploads from exceeding 512 MB.
GALLERY_PREVIEW_LOCK = Lock()
