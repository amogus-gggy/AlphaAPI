"""AlphaAPI: a Django-shaped, async-native Python web framework.

AlphaAPI keeps Django's project layout and developer ergonomics (settings,
URLconfs, function and class-based views, middleware, app registry) while using
an async-first execution model and a Rust HTTP core.  It intentionally ships
**no ORM** and no database layer.
"""

from ._core import Request, Response
from .apps import AppConfig, AppRegistry, apps
from .app import Application, import_string
from .conf import Settings, settings
from .exceptions import (
    BadRequest,
    HTTPException,
    Http404,
    PermissionDenied,
    RequestValidationError,
)
from .http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    HttpResponseNotModified,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
    QueryDict,
)
from .middleware import MiddlewareMixin
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
    # request / responses
    "Request",
    "Response",
    "HttpRequest",
    "QueryDict",
    "HttpResponse",
    "JsonResponse",
    "HttpResponseRedirect",
    "HttpResponsePermanentRedirect",
    "HttpResponseNotModified",
    "HttpResponseBadRequest",
    "HttpResponseNotFound",
    "HttpResponseForbidden",
    "HttpResponseNotAllowed",
    "HttpResponseServerError",
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
