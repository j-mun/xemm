"""Errors shared by storage and transport-independent services."""


class InvalidQuery(ValueError):
  """The request contains an invalid query or evaluation option."""


class RecordNotFound(ValueError):
  """The requested material or record does not exist."""


class AmbiguousRecord(ValueError):
  """The requested material or record resolves to multiple catalog entries."""


class DatabaseUnavailable(RuntimeError):
  """The configured material database cannot be read."""


class AuthenticationRequired(PermissionError):
  """A valid bearer token with the required permission is required."""


class RevisionConflict(RuntimeError):
  """The supplied revision does not match the current record revision."""
