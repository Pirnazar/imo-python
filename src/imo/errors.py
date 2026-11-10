"""Errors exposed by the async SDK."""


class IMOError(Exception):
    """Base class for SDK failures."""


class IMOConnectionError(IMOError):
    """The account connection is unavailable or in a conflicting state."""


class TransportError(IMOConnectionError):
    """The adapter could not complete an operation."""


class AuthenticationRequired(IMOConnectionError):
    """The adapter requires an authorized account."""


class SessionExpired(AuthenticationRequired):
    """The adapter requires fresh authorization."""


class ChatNotFound(IMOError):
    """The adapter could not find the requested chat."""


class MessageSendError(IMOError):
    """A send failed or its result is unknown. Check the chat before retrying."""


class FeatureUnavailableError(IMOError):
    """The requested operation has no configured or supported implementation."""
