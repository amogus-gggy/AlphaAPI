"""AlphaAPI: a Django-shaped, async-native Python web framework.

AlphaAPI keeps Django's project layout and developer ergonomics (settings,
URLconfs, function and class-based views, middleware, app registry) while using
an async-first execution model and a Rust HTTP core.  It intentionally ships
**no ORM** and no database layer.
"""

from ._core import Request, Response
from .apps import AppConfig, AppRegistry, apps
from .app import Application, import_string
from .auth import (
    AnonymousUser,
    AuthenticationMiddleware,
    SimpleUser,
    login,
    logout,
)
from .conf import Settings, settings
from .cors import CorsMiddleware
from .csrf import CsrfMiddleware, get_token
from .exceptions import (
    BadRequest,
    HTTPException,
    Http404,
    PermissionDenied,
    RequestValidationError,
)
from .http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseConflict,
    HttpResponseForbidden,
    HttpResponseGatewayTimeout,
    HttpResponseGone,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseNotModified,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    HttpResponseServerError,
    HttpResponseServiceUnavailable,
    HttpResponseTooManyRequests,
    JsonResponse,
    QueryDict,
    SseResponse,
    StreamingHttpResponse,
    UploadedFile,
)
from .middleware import MiddlewareMixin
from .observability import (
    Metrics,
    MetricsMiddleware,
    RequestIdMiddleware,
    health_response,
    metrics,
    metrics_response,
    readiness_response,
)
from .params import Body, Header, Param, Path, Query
from .security import SecurityMiddleware
from .sessions import MemorySessionStore, Session, SessionMiddleware, SessionStore
from .signed_cookies import dumps as dumps_signed, loads as loads_signed
from .staticfiles import StaticFiles, static
from .templates import TemplateEngine, TemplateResponse, render
from .testing import Client, ClientResponse
from .urls import (
    NoReverseMatch,
    PathConverter,
    URLPattern,
    URLResolver,
    include,
    path,
    register_converter,
    resolve,
    reverse,
)
from .views import RedirectView, View

__version__ = "0.1.0"

__all__ = [
    # application / configuration
    "Application",
    "AppConfig",
    "AppRegistry",
    "apps",
    "settings",
    "Settings",
    # URLs
    "path",
    "include",
    "reverse",
    "resolve",
    "register_converter",
    "URLPattern",
    "URLResolver",
    "PathConverter",
    "NoReverseMatch",
    # views
    "View",
    "RedirectView",
    "MiddlewareMixin",
    # parameter markers
    "Param",
    "Query",
    "Header",
    "Body",
    "Path",
    # request / responses
    "Request",
    "Response",
    "HttpRequest",
    "QueryDict",
    "UploadedFile",
    "HttpResponse",
    "JsonResponse",
    "StreamingHttpResponse",
    "SseResponse",
    "FileResponse",
    "HttpResponseRedirect",
    "HttpResponsePermanentRedirect",
    "HttpResponseNotModified",
    "HttpResponseBadRequest",
    "HttpResponseNotFound",
    "HttpResponseForbidden",
    "HttpResponseNotAllowed",
    "HttpResponseServerError",
    "HttpResponseConflict",
    "HttpResponseGone",
    "HttpResponseTooManyRequests",
    "HttpResponseServiceUnavailable",
    "HttpResponseGatewayTimeout",
    # security / middleware
    "SecurityMiddleware",
    "CorsMiddleware",
    "CsrfMiddleware",
    "get_token",
    "SessionMiddleware",
    "Session",
    "SessionStore",
    "MemorySessionStore",
    "AuthenticationMiddleware",
    "AnonymousUser",
    "SimpleUser",
    "login",
    "logout",
    "RequestIdMiddleware",
    "MetricsMiddleware",
    "Metrics",
    "metrics",
    "metrics_response",
    "health_response",
    "readiness_response",
    "dumps_signed",
    "loads_signed",
    # templates / static / testing
    "TemplateEngine",
    "TemplateResponse",
    "render",
    "StaticFiles",
    "static",
    "Client",
    "ClientResponse",
    # exceptions
    "HTTPException",
    "Http404",
    "PermissionDenied",
    "BadRequest",
    "RequestValidationError",
    # misc
    "import_string",
    "__version__",
]
