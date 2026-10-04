class PermanentIngestionError(Exception):
    """Retrying will not help (unsupported, corrupt or unparseable file)."""
