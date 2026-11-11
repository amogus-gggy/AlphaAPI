use std::borrow::Cow;
use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use bytes::{Bytes, BytesMut};
use http::header::{CONTENT_LENGTH, CONTENT_TYPE, SERVER};
use http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use http_body_util::{BodyExt, Full};
use hyper::body::{Body as _, Incoming};
use hyper::service::service_fn;
use hyper::{Request as HyperRequest, Response as HyperResponse};
use hyper_util::rt::TokioIo;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyList, PyString, PyTuple};
use pyo3::IntoPyObjectExt;
use tokio::net::TcpListener;
use tokio::sync::Notify;

use crate::request::Request;
use crate::response::Response;
use crate::spec::{ParamKind, ParamSpec, RouteSpec, TypeKind};
use crate::util::json_bytes;

const NOT_FOUND_BODY: &[u8] = b"{\"detail\":\"Not Found\"}";
const METHOD_NOT_ALLOWED_BODY: &[u8] = b"{\"detail\":\"Method Not Allowed\"}";
const INTERNAL_ERROR_BODY: &[u8] = b"{\"detail\":\"Internal Server Error\"}";
const PAYLOAD_TOO_LARGE_BODY: &[u8] = b"{\"detail\":\"Request body too large\"}";
const BAD_REQUEST_BODY: &[u8] = b"{\"detail\":\"Bad Request\"}";

// ---------------------------------------------------------------------------
// Python asyncio bridge
// ---------------------------------------------------------------------------

/// A dedicated Python event loop thread used to drive `async def` handlers.
struct PyLoop {
    locals: pyo3_async_runtimes::TaskLocals,
    loop_obj: Py<PyAny>,
    thread: Mutex<Option<std::thread::JoinHandle<()>>>,
}

impl PyLoop {
    fn start(py: Python<'_>) -> PyResult<Arc<Self>> {
        let asyncio = py.import("asyncio")?;
        let loop_obj = asyncio.call_method0("new_event_loop")?;
        let locals = pyo3_async_runtimes::TaskLocals::new(loop_obj.clone());
        let loop_for_thread = loop_obj.clone().unbind();

        let handle = std::thread::Builder::new()
            .name("alphaapi-asyncio".to_string())
            .spawn(move || {
                Python::attach(|py| {
                    let bound = loop_for_thread.bind(py);
                    if let Ok(asyncio) = py.import("asyncio") {
                        let _ = asyncio.call_method1("set_event_loop", (bound,));
                    }
                    if let Err(error) = bound.call_method0("run_forever") {
                        error.print(py);
                    }
                    let _ = bound.call_method0("close");
                });
            })?;

        Ok(Arc::new(Self {
            locals,
            loop_obj: loop_obj.unbind(),
            thread: Mutex::new(Some(handle)),
        }))
    }

    fn future<'py>(
        &self,
        awaitable: Bound<'py, PyAny>,
    ) -> PyResult<impl std::future::Future<Output = PyResult<Py<PyAny>>> + Send> {
        pyo3_async_runtimes::into_future_with_locals(&self.locals, awaitable)
    }

    fn stop(&self) {
        Python::attach(|py| {
            let bound = self.loop_obj.bind(py);
            if let Ok(stop) = bound.getattr("stop") {
                let _ = bound.call_method1("call_soon_threadsafe", (stop,));
            }
        });
    }

    fn join(&self) {
        if let Some(handle) = self.thread.lock().unwrap().take() {
            let _ = handle.join();
        }
    }
}

// ---------------------------------------------------------------------------
// Routes and shared server state
// ---------------------------------------------------------------------------

struct RouteDef {
    method: Method,
    path: String,
    handler: Py<PyAny>,
    spec: RouteSpec,
}

struct ServerState {
    routes: Vec<RouteDef>,
    paths: Vec<HashMap<Method, usize>>,
    router: matchit::Router<usize>,
    exception_handlers: Vec<(Py<PyAny>, Py<PyAny>)>,
    http_exception_type: Option<Py<PyAny>>,
    max_body_size: usize,
    access_log: bool,
    event_loop: Option<Arc<PyLoop>>,
}

#[pyclass(module = "alphaapi._core")]
pub struct AppCore {
    routes: Vec<RouteDef>,
    exception_handlers: Vec<(Py<PyAny>, Py<PyAny>)>,
    http_exception_type: Option<Py<PyAny>>,
    shutdown: Arc<Notify>,
    running: Arc<AtomicBool>,
}

#[pymethods]
impl AppCore {
    #[new]
    fn new() -> Self {
        Self {
            routes: Vec::new(),
            exception_handlers: Vec::new(),
            http_exception_type: None,
            shutdown: Arc::new(Notify::new()),
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Register a handler for one HTTP method and path.
    fn add_route(
        &mut self,
        py: Python<'_>,
        method: &str,
        path: &str,
        handler: Py<PyAny>,
        spec: &Bound<'_, PyDict>,
    ) -> PyResult<()> {
        let method = Method::from_bytes(method.to_ascii_uppercase().as_bytes())
            .map_err(|_| PyValueError::new_err(format!("invalid HTTP method: {method}")))?;
        if self
            .routes
            .iter()
            .any(|route| route.method == method && route.path == path)
        {
            return Err(PyValueError::new_err(format!(
                "duplicate route: {method} {path}"
            )));
        }
        let spec = RouteSpec::from_py(py, spec)?;
        self.routes.push(RouteDef {
            method,
            path: path.to_string(),
            handler,
            spec,
        });
        Ok(())
    }

    fn add_exception_handler(&mut self, exc_type: Py<PyAny>, handler: Py<PyAny>) {
        self.exception_handlers.push((exc_type, handler));
    }

    fn set_http_exception_type(&mut self, exc_type: Py<PyAny>) {
        self.http_exception_type = Some(exc_type);
    }

    fn stop(&self) {
        self.shutdown.notify_one();
    }

    fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    #[pyo3(signature = (host = "127.0.0.1", port = 8000, workers = None, max_body_size = None, access_log = None))]
    fn run(
        &self,
        py: Python<'_>,
        host: &str,
        port: u16,
        workers: Option<usize>,
        max_body_size: Option<usize>,
        access_log: Option<bool>,
    ) -> PyResult<()> {
        if self
            .running
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(PyRuntimeError::new_err("server is already running"));
        }

        let result = self.run_inner(
            py,
            host,
            port,
            workers,
            max_body_size.unwrap_or(16 * 1024 * 1024),
            access_log.unwrap_or(false),
        );
        self.running.store(false, Ordering::SeqCst);
        result
    }
}

impl AppCore {
    fn run_inner(
        &self,
        py: Python<'_>,
        host: &str,
        port: u16,
        workers: Option<usize>,
        max_body_size: usize,
        access_log: bool,
    ) -> PyResult<()> {
        // Build the matchit router.
        let mut router: matchit::Router<usize> = matchit::Router::new();
        let mut paths: Vec<HashMap<Method, usize>> = Vec::new();
        let mut path_ids: HashMap<String, usize> = HashMap::new();

        for (index, route) in self.routes.iter().enumerate() {
            let path_id = match path_ids.get(&route.path) {
                Some(id) => *id,
                None => {
                    let id = paths.len();
                    router.insert(route.path.clone(), id).map_err(|error| {
                        PyValueError::new_err(format!(
                            "invalid route path {:?}: {error}",
                            route.path
                        ))
                    })?;
                    paths.push(HashMap::new());
                    path_ids.insert(route.path.clone(), id);
                    id
                }
            };
            paths[path_id].insert(route.method.clone(), index);
        }

        let event_loop = if self.routes.iter().any(|route| route.spec.is_async) {
            Some(PyLoop::start(py)?)
        } else {
            None
        };

        // Clone Python references while the GIL is held.
        let routes: Vec<RouteDef> = self
            .routes
            .iter()
            .map(|route| RouteDef {
                method: route.method.clone(),
                path: route.path.clone(),
                handler: route.handler.clone_ref(py),
                spec: RouteSpec {
                    params: route
                        .spec
                        .params
                        .iter()
                        .map(|param| ParamSpec {
                            name: param.name.clone(),
                            kind: param.kind,
                            ty: param.ty,
                            required: param.required,
                            default: param.default.as_ref().map(|value| value.clone_ref(py)),
                            model: param.model.as_ref().map(|value| value.clone_ref(py)),
                            positional: param.positional,
                            alias: param.alias.clone(),
                        })
                        .collect(),
                    is_async: route.spec.is_async,
                    status_code: route.spec.status_code,
                    needs_request: route.spec.needs_request,
                    has_body: route.spec.has_body,
                    has_header_params: route.spec.has_header_params,
                    has_query_params: route.spec.has_query_params,
                    has_path_params: route.spec.has_path_params,
                },
            })
            .collect();

        let exception_handlers = self
            .exception_handlers
            .iter()
            .map(|(exc_type, handler)| (exc_type.clone_ref(py), handler.clone_ref(py)))
            .collect();
        let http_exception_type = self
            .http_exception_type
            .as_ref()
            .map(|value| value.clone_ref(py));

        let state = Arc::new(ServerState {
            routes,
            paths,
            router,
            exception_handlers,
            http_exception_type,
            max_body_size,
            access_log,
            event_loop: event_loop.clone(),
        });

        // Python execution is serialized by the GIL, so extra Tokio workers
        // mostly add context switching and lock contention.  Half the cores
        // (minimum one) keeps networking responsive without that overhead;
        // callers can raise `workers=` when sync handlers block on I/O.
        let worker_threads = workers.unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|count| count.get().saturating_add(1) / 2)
                .unwrap_or(1)
                .max(1)
        });

        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(worker_threads.max(1))
            .enable_all()
            .build()
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        let shutdown = self.shutdown.clone();
        let address = format!("{host}:{port}");
        let serve_state = state.clone();
        let server_result =
            py.detach(move || runtime.block_on(serve(serve_state, shutdown, address)));

        if let Some(event_loop) = &event_loop {
            event_loop.stop();
            py.detach(|| event_loop.join());
        }

        server_result.map_err(|error| PyRuntimeError::new_err(error.to_string()))
    }
}

// ---------------------------------------------------------------------------
// Server
// ---------------------------------------------------------------------------

async fn serve(
    state: Arc<ServerState>,
    shutdown: Arc<Notify>,
    address: String,
) -> std::io::Result<()> {
    let listener = TcpListener::bind(&address).await?;
    println!("AlphaAPI running on http://{address}");

    loop {
        tokio::select! {
            _ = shutdown.notified() => break,
            signal = tokio::signal::ctrl_c() => {
                let _ = signal;
                break;
            }
            accepted = listener.accept() => {
                let (stream, peer) = match accepted {
                    Ok(value) => value,
                    Err(_) => continue,
                };
                // Latency matters more than packet efficiency for API traffic.
                let _ = stream.set_nodelay(true);
                let io = TokioIo::new(stream);
                let state = state.clone();
                let client = peer.ip();

                tokio::spawn(async move {
                    let service = service_fn(move |request: HyperRequest<Incoming>| {
                        let state = state.clone();
                        async move {
                            Ok::<_, std::convert::Infallible>(
                                handle_request(request, state, client).await,
                            )
                        }
                    });
                    // HTTP/1 is the overwhelming majority of API traffic and
                    // avoids the protocol-detection overhead of the auto
                    // (HTTP/1 + HTTP/2) builder.
                    let _ = hyper::server::conn::http1::Builder::new()
                        .keep_alive(true)
                        .pipeline_flush(true)
                        .serve_connection(io, service)
                        .await;
                });
            }
        }
    }

    Ok(())
}

async fn handle_request(
    request: HyperRequest<Incoming>,
    state: Arc<ServerState>,
    client: IpAddr,
) -> HyperResponse<Full<Bytes>> {
    let started = Instant::now();
    let (parts, incoming) = request.into_parts();
    let method = parts.method;
    let path = parts.uri.path();
    let query = parts.uri.query().unwrap_or("");
    let log_path = if state.access_log {
        Some(path.to_string())
    } else {
        None
    };

    // Route first, so we know exactly which request data the handler needs.
    let matched = match state.router.at(path) {
        Ok(matched) => matched,
        Err(_) => {
            return BuiltResponse::static_json(StatusCode::NOT_FOUND, NOT_FOUND_BODY)
                .into_hyper(false)
        }
    };
    let path_id = *matched.value;

    let methods = &state.paths[path_id];

    // Automatic OPTIONS response.
    if method == Method::OPTIONS && !methods.contains_key(&Method::OPTIONS) {
        let allow = allow_header(methods);
        return BuiltResponse::empty(StatusCode::NO_CONTENT, vec![("allow".to_string(), allow)])
            .into_hyper(false);
    }

    let route_index = match methods.get(&method) {
        Some(index) => *index,
        None if method == Method::HEAD => match methods.get(&Method::GET) {
            Some(index) => *index,
            None => return method_not_allowed(methods),
        },
        None => return method_not_allowed(methods),
    };

    let spec = &state.routes[route_index].spec;
    let has_handlers = !state.exception_handlers.is_empty();
    // A request object is needed if the handler declares one, or if a custom
    // exception handler might need to inspect it.
    let full_request = spec.needs_request || has_handlers;
    let needs_headers = full_request || spec.has_header_params;
    let needs_query = full_request || spec.has_query_params;

    let params = if (spec.has_path_params || full_request) && !matched.params.is_empty() {
        let mut params = Vec::with_capacity(matched.params.len());
        for (key, value) in matched.params.iter() {
            params.push((key.to_string(), value.to_string()));
        }
        params
    } else {
        Vec::new()
    };

    // Only materialize the pieces the route actually asked for.
    let path_string = full_request.then(|| path.to_string());
    let query_string = full_request.then(|| query.to_string());
    let query_map = needs_query.then(|| parse_query(query));
    let headers = if needs_headers {
        Some(parts.headers)
    } else {
        None
    };

    let body = if incoming.is_end_stream() {
        Bytes::new()
    } else {
        match read_body(incoming, state.max_body_size).await {
            Ok(body) => body,
            Err(BodyError::TooLarge) => {
                return BuiltResponse::static_json(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    PAYLOAD_TOO_LARGE_BODY,
                )
                .into_hyper(false)
            }
            Err(BodyError::Read) => {
                return BuiltResponse::static_json(StatusCode::BAD_REQUEST, BAD_REQUEST_BODY)
                    .into_hyper(false)
            }
        }
    };

    let request_data = RequestData {
        method: method.clone(),
        path: path_string,
        query_string,
        client: full_request.then(|| client.to_string()),
        headers,
        params,
        query: query_map,
        body,
    };

    let is_head = method == Method::HEAD;
    let built = dispatch(state.clone(), route_index, request_data).await;
    let status = built.status;
    let response = built.into_hyper(is_head);
    if state.access_log {
        eprintln!(
            "{} {} {} {:.2}ms",
            method,
            log_path.as_deref().unwrap_or(""),
            status.as_u16(),
            started.elapsed().as_secs_f64() * 1000.0
        );
    }
    response
}

enum BodyError {
    TooLarge,
    Read,
}

/// Collect a request body with a size limit.
///
/// The common case (one data frame) is returned without copying: the frame's
/// `Bytes` buffer is used directly.  Multiple frames are merged exactly once.
async fn read_body(mut body: Incoming, max_size: usize) -> Result<Bytes, BodyError> {
    let mut buffer: Option<Bytes> = None;
    let mut total = 0usize;

    while let Some(frame) = body.frame().await {
        let frame = frame.map_err(|_| BodyError::Read)?;
        let data = match frame.into_data() {
            Ok(data) => data,
            Err(_) => continue,
        };

        total = total.saturating_add(data.len());
        if total > max_size {
            return Err(BodyError::TooLarge);
        }

        buffer = Some(match buffer {
            None => data,
            Some(existing) => {
                let mut merged = BytesMut::with_capacity(total);
                merged.extend_from_slice(&existing);
                merged.extend_from_slice(&data);
                merged.freeze()
            }
        });
    }

    Ok(buffer.unwrap_or_default())
}

fn method_not_allowed(methods: &HashMap<Method, usize>) -> HyperResponse<Full<Bytes>> {
    let allow = allow_header(methods);
    BuiltResponse::static_json(StatusCode::METHOD_NOT_ALLOWED, METHOD_NOT_ALLOWED_BODY)
        .with_header("allow", allow)
        .into_hyper(false)
}

fn allow_header(methods: &HashMap<Method, usize>) -> String {
    let mut names: Vec<&str> = methods.keys().map(|method| method.as_str()).collect();
    if methods.contains_key(&Method::GET) && !methods.contains_key(&Method::HEAD) {
        names.push("HEAD");
    }
    if !methods.contains_key(&Method::OPTIONS) {
        names.push("OPTIONS");
    }
    names.sort_unstable();
    names.join(", ")
}

fn parse_query(query: &str) -> HashMap<String, Vec<String>> {
    if query.is_empty() {
        return HashMap::new();
    }

    let pairs = query.bytes().filter(|byte| *byte == b'&').count() + 1;
    let mut result: HashMap<String, Vec<String>> = HashMap::with_capacity(pairs);
    for (key, value) in form_urlencoded::parse(query.as_bytes()) {
        result
            .entry(key.into_owned())
            .or_default()
            .push(value.into_owned());
    }
    result
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

struct RequestData {
    method: Method,
    path: Option<String>,
    query_string: Option<String>,
    client: Option<String>,
    headers: Option<HeaderMap>,
    params: Vec<(String, String)>,
    query: Option<HashMap<String, Vec<String>>>,
    body: Bytes,
}

impl RequestData {
    fn to_request(&self) -> Request {
        Request::new(
            self.method.clone(),
            self.path.clone().unwrap_or_default(),
            self.query_string.clone().unwrap_or_default(),
            self.client.clone(),
            self.headers.clone().unwrap_or_default(),
            self.params.clone(),
            self.query.clone().unwrap_or_default(),
            self.body.clone(),
        )
    }
}

#[derive(Debug)]
struct ValidationFailure {
    loc: Vec<String>,
    msg: String,
    kind: String,
}

impl ValidationFailure {
    fn new(kind: &str, alias: &str, msg: impl Into<String>, error_kind: &str) -> Self {
        Self {
            loc: vec![kind.to_string(), alias.to_string()],
            msg: msg.into(),
            kind: error_kind.to_string(),
        }
    }

    fn missing(param: &ParamSpec) -> Self {
        Self::new(
            param_kind_name(param.kind),
            &param.alias,
            "Field required",
            "missing",
        )
    }

    fn from_python(param: &ParamSpec, error: PyErr) -> Self {
        Self::new(
            param_kind_name(param.kind),
            &param.alias,
            error.to_string(),
            "value_error",
        )
    }
}

fn param_kind_name(kind: ParamKind) -> &'static str {
    match kind {
        ParamKind::Path => "path",
        ParamKind::Query => "query",
        ParamKind::Header => "header",
        ParamKind::Body => "body",
        ParamKind::Request => "request",
    }
}

enum CallError {
    Validation(ValidationFailure),
    Python(PyErr),
}

impl From<PyErr> for CallError {
    fn from(error: PyErr) -> Self {
        CallError::Python(error)
    }
}

async fn dispatch(
    state: Arc<ServerState>,
    route_index: usize,
    request: RequestData,
) -> BuiltResponse {
    if state.routes[route_index].spec.is_async {
        dispatch_async(state, route_index, request).await
    } else {
        // Run short synchronous handlers directly on the current worker.  The
        // GIL serializes Python execution anyway, so a thread-pool round-trip
        // only adds latency.
        Python::attach(|py| dispatch_blocking(py, &state, route_index, &request))
    }
}

fn dispatch_blocking(
    py: Python<'_>,
    state: &ServerState,
    route_index: usize,
    request: &RequestData,
) -> BuiltResponse {
    let route = &state.routes[route_index];
    match call_handler(py, route, request) {
        Ok(value) => serialize_result(py, value, route.spec.status_code),
        Err(CallError::Validation(failure)) => validation_response(failure),
        Err(CallError::Python(error)) => handle_python_error(py, state, error, request),
    }
}

async fn dispatch_async(
    state: Arc<ServerState>,
    route_index: usize,
    request: RequestData,
) -> BuiltResponse {
    // Calling an `async def` handler only creates a coroutine, so it is cheap
    // enough to do inline instead of paying for a blocking-pool round-trip.
    let awaitable =
        match Python::attach(|py| call_handler(py, &state.routes[route_index], &request)) {
            Ok(awaitable) => awaitable,
            Err(CallError::Validation(failure)) => return validation_response(failure),
            Err(CallError::Python(error)) => {
                return Python::attach(|py| handle_python_error(py, &state, error, &request))
            }
        };

    let event_loop = match &state.event_loop {
        Some(event_loop) => event_loop.clone(),
        None => {
            return BuiltResponse::static_json(
                StatusCode::INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR_BODY,
            )
        }
    };

    let future = match Python::attach(|py| event_loop.future(awaitable.bind(py).clone())) {
        Ok(future) => future,
        Err(error) => return Python::attach(|py| handle_python_error(py, &state, error, &request)),
    };

    match future.await {
        Ok(value) => Python::attach(|py| {
            let status = state.routes[route_index].spec.status_code;
            serialize_result(py, value, status)
        }),
        Err(error) => Python::attach(|py| handle_python_error(py, &state, error, &request)),
    }
}

fn call_handler(
    py: Python<'_>,
    route: &RouteDef,
    request: &RequestData,
) -> Result<Py<PyAny>, CallError> {
    let spec = &route.spec;
    let request_object = if spec.needs_request {
        Some(
            Py::new(py, request.to_request())
                .map_err(CallError::Python)?
                .into_any(),
        )
    } else {
        None
    };

    let mut args: Vec<Py<PyAny>> = Vec::with_capacity(spec.params.len());
    let mut kwargs: Option<Bound<'_, PyDict>> = None;
    let mut body_parsed: Option<Bound<'_, PyAny>> = None;

    for param in &spec.params {
        let value: Py<PyAny> = match param.kind {
            ParamKind::Request => request_object
                .as_ref()
                .expect("request object must exist")
                .clone_ref(py),
            ParamKind::Path => {
                let raw = request
                    .params
                    .iter()
                    .find(|(key, _)| key == &param.alias)
                    .map(|(_, value)| value.as_str())
                    .ok_or_else(|| CallError::Validation(ValidationFailure::missing(param)))?;
                convert_scalar(py, param, raw)?
            }
            ParamKind::Header => match request
                .headers
                .as_ref()
                .and_then(|headers| headers.get(param.alias.as_str()))
            {
                Some(raw) => {
                    let raw = raw.to_str().map_err(|_| {
                        CallError::Validation(ValidationFailure::new(
                            "header",
                            &param.alias,
                            "Header value is not valid UTF-8",
                            "value_error",
                        ))
                    })?;
                    convert_scalar(py, param, raw)?
                }
                None => missing_value(py, param)?,
            },
            ParamKind::Query => match request
                .query
                .as_ref()
                .and_then(|query| query.get(&param.alias))
            {
                Some(values) if !values.is_empty() => {
                    if param.ty == TypeKind::StrList {
                        PyList::new(py, values.iter().map(|value| value.as_str()))
                            .map_err(CallError::Python)?
                            .into_any()
                            .unbind()
                    } else {
                        convert_scalar(py, param, values.last().unwrap())?
                    }
                }
                _ => missing_value(py, param)?,
            },
            ParamKind::Body => {
                if param.ty == TypeKind::Bytes {
                    if request.body.is_empty() {
                        missing_value(py, param)?
                    } else {
                        PyBytes::new(py, &request.body).into_any().unbind()
                    }
                } else if body_parsed.is_none() {
                    if request.body.is_empty() {
                        body_parsed = Some(py.None().into_bound(py));
                    } else {
                        let value: serde_json::Value = serde_json::from_slice(&request.body)
                            .map_err(|error| {
                                CallError::Validation(ValidationFailure::new(
                                    "body",
                                    &param.alias,
                                    format!("Invalid JSON: {error}"),
                                    "json_invalid",
                                ))
                            })?;
                        body_parsed = Some(
                            pythonize::pythonize(py, &value)
                                .map_err(|error| CallError::Python(error.into()))?,
                        );
                    }

                    let parsed = body_parsed.as_ref().unwrap();
                    if parsed.is_none() {
                        missing_value(py, param)?
                    } else if param.ty == TypeKind::Model {
                        construct_model(py, param, parsed)?
                    } else {
                        parsed.clone().unbind()
                    }
                } else {
                    let parsed = body_parsed.as_ref().unwrap();
                    if parsed.is_none() {
                        missing_value(py, param)?
                    } else if param.ty == TypeKind::Model {
                        construct_model(py, param, parsed)?
                    } else {
                        parsed.clone().unbind()
                    }
                }
            }
        };

        if param.positional {
            args.push(value);
        } else {
            let dict = kwargs.get_or_insert_with(|| PyDict::new(py));
            dict.set_item(&param.name, value)
                .map_err(CallError::Python)?;
        }
    }

    let args = PyTuple::new(py, args).map_err(CallError::Python)?;
    route
        .handler
        .call(py, args, kwargs.as_ref())
        .map_err(CallError::Python)
}

fn missing_value(py: Python<'_>, param: &ParamSpec) -> Result<Py<PyAny>, CallError> {
    if param.required {
        Err(CallError::Validation(ValidationFailure::missing(param)))
    } else {
        Ok(param
            .default
            .as_ref()
            .map(|value| value.clone_ref(py))
            .unwrap_or_else(|| py.None()))
    }
}

fn convert_scalar(py: Python<'_>, param: &ParamSpec, raw: &str) -> Result<Py<PyAny>, CallError> {
    match param.ty {
        TypeKind::Str | TypeKind::Json | TypeKind::Model | TypeKind::Bytes => {
            Ok(PyString::new(py, raw).into_any().unbind())
        }
        TypeKind::Int => raw
            .parse::<i64>()
            .map_err(|_| {
                CallError::Validation(ValidationFailure::new(
                    param_kind_name(param.kind),
                    &param.alias,
                    "Input should be a valid integer",
                    "int_parsing",
                ))
            })?
            .into_py_any(py)
            .map_err(CallError::Python),
        TypeKind::Float => raw
            .parse::<f64>()
            .map_err(|_| {
                CallError::Validation(ValidationFailure::new(
                    param_kind_name(param.kind),
                    &param.alias,
                    "Input should be a valid number",
                    "float_parsing",
                ))
            })?
            .into_py_any(py)
            .map_err(CallError::Python),
        TypeKind::Bool => {
            let value = match raw.to_ascii_lowercase().as_str() {
                "1" | "true" | "yes" | "on" => true,
                "0" | "false" | "no" | "off" => false,
                _ => {
                    return Err(CallError::Validation(ValidationFailure::new(
                        param_kind_name(param.kind),
                        &param.alias,
                        "Input should be a valid boolean",
                        "bool_parsing",
                    )))
                }
            };
            value.into_py_any(py).map_err(CallError::Python)
        }
        TypeKind::StrList => Ok(PyList::new(py, [raw])
            .map_err(CallError::Python)?
            .into_any()
            .unbind()),
    }
}

fn construct_model(
    py: Python<'_>,
    param: &ParamSpec,
    data: &Bound<'_, PyAny>,
) -> Result<Py<PyAny>, CallError> {
    let model = param
        .model
        .as_ref()
        .ok_or_else(|| {
            CallError::Validation(ValidationFailure::new(
                "body",
                &param.alias,
                "Model class is missing",
                "model_missing",
            ))
        })?
        .bind(py);

    let result = if model.hasattr("model_validate").map_err(CallError::Python)? {
        model.call_method1("model_validate", (data,))
    } else if model.hasattr("parse_obj").map_err(CallError::Python)? {
        model.call_method1("parse_obj", (data,))
    } else if let Ok(dict) = data.cast::<PyDict>() {
        model.call((), Some(dict))
    } else {
        model.call1((data,))
    };

    result
        .map(Bound::unbind)
        .map_err(|error| CallError::Validation(ValidationFailure::from_python(param, error)))
}

fn validation_response(failure: ValidationFailure) -> BuiltResponse {
    let detail = serde_json::json!({
        "detail": [{
            "loc": failure.loc,
            "msg": failure.msg,
            "type": failure.kind,
        }]
    });
    BuiltResponse::json_vec(
        StatusCode::UNPROCESSABLE_ENTITY,
        serde_json::to_vec(&detail).unwrap_or_else(|_| b"{\"detail\":[]}".to_vec()),
        Vec::new(),
    )
}

fn handle_python_error(
    py: Python<'_>,
    state: &ServerState,
    error: PyErr,
    request: &RequestData,
) -> BuiltResponse {
    // User supplied exception handlers take precedence so applications can
    // override the built-in HTTPException rendering.
    for (exc_type, handler) in &state.exception_handlers {
        if error.is_instance(py, exc_type.bind(py)) {
            let request_object = match Py::new(py, request.to_request()) {
                Ok(request) => request.into_any(),
                Err(inner) => {
                    inner.print(py);
                    break;
                }
            };
            let exception = error.value(py).clone().into_any().unbind();
            match handler.call1(py, (request_object, exception)) {
                Ok(value) => return serialize_result(py, value, 200),
                Err(handler_error) => {
                    handler_error.print(py);
                    break;
                }
            }
        }
    }

    // Built-in HTTPException support.
    if let Some(exc_type) = &state.http_exception_type {
        if error.is_instance(py, exc_type.bind(py)) {
            let value = error.value(py);
            let status = value
                .getattr("status_code")
                .ok()
                .and_then(|status| status.extract::<u16>().ok())
                .unwrap_or(500);
            let detail = value
                .getattr("detail")
                .ok()
                .and_then(|detail| json_bytes(py, &detail).ok())
                .unwrap_or_else(|| b"null".to_vec());
            let mut body = Vec::with_capacity(detail.len() + 11);
            body.extend_from_slice(b"{\"detail\":");
            body.extend_from_slice(&detail);
            body.push(b'}');

            let mut headers = Vec::new();
            if let Ok(header_dict) = value.getattr("headers") {
                if let Ok(header_dict) = header_dict.cast::<PyDict>() {
                    for (key, value) in header_dict.iter() {
                        if let (Ok(key), Ok(value)) =
                            (key.extract::<String>(), value.extract::<String>())
                        {
                            headers.push((key, value));
                        }
                    }
                }
            }

            return BuiltResponse::json_vec(
                StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                body,
                headers,
            );
        }
    }

    error.print(py);
    BuiltResponse::static_json(StatusCode::INTERNAL_SERVER_ERROR, INTERNAL_ERROR_BODY)
}

fn serialize_result(py: Python<'_>, value: Py<PyAny>, default_status: u16) -> BuiltResponse {
    let value = value.bind(py);

    if let Some(response) = Response::from_instance(value) {
        let status =
            StatusCode::from_u16(response.status_code).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
        return BuiltResponse {
            status,
            headers: response.headers,
            body: Bytes::from(response.body),
            media_type: response.media_type.map(Cow::Owned),
        };
    }

    if value.is_none() {
        return BuiltResponse::json(
            StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            Bytes::from_static(b"null"),
            Vec::new(),
        );
    }

    if let Ok(bytes) = value.cast::<PyBytes>() {
        return BuiltResponse {
            status: StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            headers: Vec::new(),
            body: Bytes::copy_from_slice(bytes.as_bytes()),
            media_type: Some(Cow::Borrowed("application/octet-stream")),
        };
    }

    if let Ok(bytes) = value.cast::<PyByteArray>() {
        return BuiltResponse {
            status: StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            headers: Vec::new(),
            body: Bytes::from(bytes.to_vec()),
            media_type: Some(Cow::Borrowed("application/octet-stream")),
        };
    }

    if let Ok(text) = value.cast::<PyString>() {
        return BuiltResponse {
            status: StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            headers: Vec::new(),
            body: Bytes::from(text.to_string_lossy().into_owned().into_bytes()),
            media_type: Some(Cow::Borrowed("text/plain; charset=utf-8")),
        };
    }

    match json_bytes(py, value) {
        Ok(body) => BuiltResponse::json_vec(
            StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            body,
            Vec::new(),
        ),
        Err(error) => {
            error.print(py);
            BuiltResponse::static_json(StatusCode::INTERNAL_SERVER_ERROR, INTERNAL_ERROR_BODY)
        }
    }
}

// ---------------------------------------------------------------------------
// HTTP responses
// ---------------------------------------------------------------------------

struct BuiltResponse {
    status: StatusCode,
    headers: Vec<(String, String)>,
    body: Bytes,
    media_type: Option<Cow<'static, str>>,
}

impl BuiltResponse {
    fn json(status: StatusCode, body: Bytes, headers: Vec<(String, String)>) -> Self {
        Self {
            status,
            headers,
            body,
            media_type: Some(Cow::Borrowed("application/json")),
        }
    }

    fn json_vec(status: StatusCode, body: Vec<u8>, headers: Vec<(String, String)>) -> Self {
        Self::json(status, Bytes::from(body), headers)
    }

    fn static_json(status: StatusCode, body: &'static [u8]) -> Self {
        Self::json(status, Bytes::from_static(body), Vec::new())
    }

    fn empty(status: StatusCode, headers: Vec<(String, String)>) -> Self {
        Self {
            status,
            headers,
            body: Bytes::new(),
            media_type: None,
        }
    }

    fn with_header(mut self, key: &str, value: String) -> Self {
        self.headers.push((key.to_string(), value));
        self
    }

    fn into_hyper(self, head: bool) -> HyperResponse<Full<Bytes>> {
        let status = self.status;
        let length = self.body.len();
        let no_body = status == StatusCode::NO_CONTENT || status == StatusCode::NOT_MODIFIED;
        let body = if head || no_body {
            Bytes::new()
        } else {
            self.body
        };

        let mut response = HyperResponse::new(Full::new(body));
        *response.status_mut() = status;
        let headers = response.headers_mut();

        for (key, value) in &self.headers {
            if let (Ok(name), Ok(value)) = (
                HeaderName::from_bytes(key.as_bytes()),
                HeaderValue::from_str(value),
            ) {
                headers.append(name, value);
            }
        }

        if !headers.contains_key(CONTENT_TYPE) {
            if let Some(media_type) = &self.media_type {
                if let Ok(value) = HeaderValue::from_str(media_type.as_ref()) {
                    headers.insert(CONTENT_TYPE, value);
                }
            }
        }

        if !headers.contains_key(CONTENT_LENGTH) && !no_body {
            let mut buffer = itoa::Buffer::new();
            if let Ok(value) = HeaderValue::from_str(buffer.format(length)) {
                headers.insert(CONTENT_LENGTH, value);
            }
        }

        if !headers.contains_key(SERVER) {
            headers.insert(SERVER, HeaderValue::from_static("alphaapi"));
        }

        response
    }
}
