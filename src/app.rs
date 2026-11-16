use std::borrow::Cow;
use std::collections::HashMap;
use std::convert::Infallible;
use std::net::IpAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use bytes::{Bytes, BytesMut};
use http::header::{CONTENT_LENGTH, CONTENT_TYPE, HOST, SERVER};
use http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use http_body_util::{BodyExt, Full};
use hyper::body::{Body as _, Frame, Incoming};
use hyper::service::service_fn;
use hyper::{Request as HyperRequest, Response as HyperResponse};
use hyper_util::rt::{TokioExecutor, TokioIo};
use hyper_util::server::conn::auto;
use pyo3::exceptions::{PyRuntimeError, PyStopAsyncIteration, PyStopIteration, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyList, PyString, PyTuple};
use pyo3::IntoPyObjectExt;
use tokio::net::TcpListener;
use tokio::sync::{mpsc, Notify, Semaphore};

use crate::request::Request;
use crate::response::Response;
use crate::spec::{ParamKind, ParamSpec, RouteSpec, TypeKind};
use crate::util::json_bytes;

const NOT_FOUND_BODY: &[u8] = b"{\"detail\":\"Not Found\"}";
const METHOD_NOT_ALLOWED_BODY: &[u8] = b"{\"detail\":\"Method Not Allowed\"}";
const INTERNAL_ERROR_BODY: &[u8] = b"{\"detail\":\"Internal Server Error\"}";
const PAYLOAD_TOO_LARGE_BODY: &[u8] = b"{\"detail\":\"Request body too large\"}";
const BAD_REQUEST_BODY: &[u8] = b"{\"detail\":\"Bad Request\"}";
const SERVICE_UNAVAILABLE_BODY: &[u8] = b"{\"detail\":\"Service Unavailable\"}";
const GATEWAY_TIMEOUT_BODY: &[u8] = b"{\"detail\":\"Gateway Timeout\"}";

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

#[derive(Clone)]
struct ServerConfig {
    allowed_hosts: Vec<String>,
    trusted_proxies: Vec<String>,
    trust_proxy_headers: bool,
    debug: bool,
    access_log_json: bool,
    security_headers: bool,
    hsts_seconds: u64,
    hsts_include_subdomains: bool,
    referrer_policy: String,
    x_frame_options: String,
    request_timeout: Option<Duration>,
    max_concurrent_requests: Option<usize>,
    offload_sync_views: bool,
    http2_max_concurrent_streams: Option<u32>,
    http2_initial_window_size: Option<u32>,
    http2_keep_alive_interval: Option<Duration>,
    http2_keep_alive_timeout: Option<Duration>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            allowed_hosts: vec!["*".to_string()],
            trusted_proxies: Vec::new(),
            trust_proxy_headers: true,
            debug: false,
            access_log_json: false,
            security_headers: true,
            hsts_seconds: 0,
            hsts_include_subdomains: false,
            referrer_policy: "same-origin".to_string(),
            x_frame_options: "DENY".to_string(),
            request_timeout: None,
            max_concurrent_requests: None,
            offload_sync_views: false,
            http2_max_concurrent_streams: None,
            http2_initial_window_size: None,
            http2_keep_alive_interval: None,
            http2_keep_alive_timeout: None,
        }
    }
}

fn config_bool(dict: &Bound<'_, PyDict>, key: &str, default: bool) -> PyResult<bool> {
    match dict.get_item(key)? {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(default),
    }
}

fn config_int<T>(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<T>>
where
    T: for<'a, 'py> pyo3::FromPyObject<'a, 'py>,
{
    match dict.get_item(key)? {
        Some(value) if !value.is_none() => Ok(Some(value.extract().map_err(Into::into)?)),
        _ => Ok(None),
    }
}

fn config_string(dict: &Bound<'_, PyDict>, key: &str, default: &str) -> PyResult<String> {
    match dict.get_item(key)? {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(default.to_string()),
    }
}

fn config_strings(
    dict: &Bound<'_, PyDict>,
    key: &str,
    default: Vec<String>,
) -> PyResult<Vec<String>> {
    match dict.get_item(key)? {
        Some(value) if !value.is_none() => value.extract(),
        _ => Ok(default),
    }
}

impl ServerConfig {
    fn from_py(dict: Option<&Bound<'_, PyDict>>) -> PyResult<Self> {
        let Some(dict) = dict else {
            return Ok(Self::default());
        };
        let timeout: Option<f64> = config_int(dict, "request_timeout")?;
        let keep_alive_interval: Option<f64> = config_int(dict, "http2_keep_alive_interval")?;
        let keep_alive_timeout: Option<f64> = config_int(dict, "http2_keep_alive_timeout")?;

        Ok(Self {
            allowed_hosts: config_strings(dict, "allowed_hosts", vec!["*".to_string()])?,
            trusted_proxies: config_strings(dict, "trusted_proxies", Vec::new())?,
            trust_proxy_headers: config_bool(dict, "trust_proxy_headers", true)?,
            debug: config_bool(dict, "debug", false)?,
            access_log_json: config_bool(dict, "access_log_json", false)?,
            security_headers: config_bool(dict, "security_headers", true)?,
            hsts_seconds: config_int::<u64>(dict, "hsts_seconds")?.unwrap_or(0),
            hsts_include_subdomains: config_bool(dict, "hsts_include_subdomains", false)?,
            referrer_policy: config_string(dict, "referrer_policy", "same-origin")?,
            x_frame_options: config_string(dict, "x_frame_options", "DENY")?,
            request_timeout: timeout
                .filter(|value| *value > 0.0)
                .map(Duration::from_secs_f64),
            max_concurrent_requests: config_int::<usize>(dict, "max_concurrent_requests")?,
            offload_sync_views: config_bool(dict, "offload_sync_views", false)?,
            http2_max_concurrent_streams: config_int::<u32>(dict, "http2_max_concurrent_streams")?,
            http2_initial_window_size: config_int::<u32>(dict, "http2_initial_window_size")?,
            http2_keep_alive_interval: keep_alive_interval
                .filter(|value| *value > 0.0)
                .map(Duration::from_secs_f64),
            http2_keep_alive_timeout: keep_alive_timeout
                .filter(|value| *value > 0.0)
                .map(Duration::from_secs_f64),
        })
    }
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
    config: ServerConfig,
    semaphore: Option<Arc<Semaphore>>,
}

#[pyclass(module = "alphaapi._core")]
pub struct AppCore {
    routes: Vec<RouteDef>,
    exception_handlers: Vec<(Py<PyAny>, Py<PyAny>)>,
    http_exception_type: Option<Py<PyAny>>,
    shutdown: Arc<Notify>,
    running: Arc<AtomicBool>,
    event_loop: Mutex<Option<Arc<PyLoop>>>,
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
            event_loop: Mutex::new(None),
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

    fn start_event_loop(&self, py: Python<'_>) -> PyResult<()> {
        let mut slot = self.event_loop.lock().unwrap();
        if slot.is_none() {
            *slot = Some(PyLoop::start(py)?);
        }
        Ok(())
    }

    fn stop_event_loop(&self, py: Python<'_>) {
        let event_loop = self.event_loop.lock().unwrap().take();
        if let Some(event_loop) = event_loop {
            event_loop.stop();
            // The loop thread needs the GIL to finish *after* ``stop`` is
            // scheduled, so releasing it while joining avoids a deadlock.
            py.detach(|| event_loop.join());
        }
    }

    fn run_on_event_loop(
        &self,
        py: Python<'_>,
        awaitable: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let event_loop = self
            .event_loop
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| PyRuntimeError::new_err("event loop is not running"))?;
        let asyncio = py.import("asyncio")?;
        let future = asyncio.call_method1(
            "run_coroutine_threadsafe",
            (awaitable, event_loop.loop_obj.bind(py)),
        )?;
        Ok(future.call_method0("result")?.unbind())
    }

    #[pyo3(signature = (host = "127.0.0.1", port = 8000, workers = None, max_body_size = None, access_log = None, config = None))]
    fn run(
        &self,
        py: Python<'_>,
        host: &str,
        port: u16,
        workers: Option<usize>,
        max_body_size: Option<usize>,
        access_log: Option<bool>,
        config: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<()> {
        if self
            .running
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(PyRuntimeError::new_err("server is already running"));
        }

        let server_config = match ServerConfig::from_py(config) {
            Ok(config) => config,
            Err(error) => {
                self.running.store(false, Ordering::SeqCst);
                return Err(error);
            }
        };
        let result = self.run_inner(
            py,
            host,
            port,
            workers,
            max_body_size.unwrap_or(16 * 1024 * 1024),
            access_log.unwrap_or(false),
            server_config,
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
        config: ServerConfig,
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

        // The bridge is also used for streaming responses, async exception
        // handlers, and lifecycle hooks, so start it whenever one was not
        // already supplied by the Python layer.
        let existing_loop = self.event_loop.lock().unwrap().clone();
        let (event_loop, owns_event_loop) = match existing_loop {
            Some(event_loop) => (event_loop, false),
            None => (PyLoop::start(py)?, true),
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
            event_loop: Some(event_loop.clone()),
            semaphore: config
                .max_concurrent_requests
                .filter(|limit| *limit > 0)
                .map(|limit| Arc::new(Semaphore::new(limit))),
            config,
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

        if owns_event_loop {
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
                // Snapshot of the security config for this connection, used
                // by framework-generated early responses (see BuiltResponse).
                let conn_config = state.config.clone();

                tokio::spawn(async move {
                    let builder_state = state.clone();
                    let service = service_fn(move |request: HyperRequest<Incoming>| {
                        let state = state.clone();
                        async move {
                            let permit = if let Some(semaphore) = &state.semaphore {
                                match semaphore.clone().try_acquire_owned() {
                                    Ok(permit) => Some(permit),
                                    Err(_) => {
                                        return Ok::<_, Infallible>(
                                            BuiltResponse::framework(
                                                StatusCode::SERVICE_UNAVAILABLE,
                                                SERVICE_UNAVAILABLE_BODY,
                                                &builder_state.config,
                                            )
                                            .into_hyper(false),
                                        )
                                    }
                                }
                            } else {
                                None
                            };
                            let _permit = permit;

                            let future = handle_request(request, state.clone(), client, conn_config.clone());
                            let response = if let Some(timeout) = state.config.request_timeout {
                                match tokio::time::timeout(timeout, future).await {
                                    Ok(response) => response,
                                    Err(_) => BuiltResponse::framework(
                                        StatusCode::GATEWAY_TIMEOUT,
                                        GATEWAY_TIMEOUT_BODY,
                                        &state.config,
                                    )
                                    .into_hyper(false),
                                }
                            } else {
                                future.await
                            };
                            Ok::<_, Infallible>(response)
                        }
                    });
                    // Detect HTTP/1 vs HTTP/2 (cleartext, prior knowledge)
                    // from the first bytes on the connection. TLS is expected
                    // to be terminated by a reverse proxy.
                    let mut builder = auto::Builder::new(TokioExecutor::new());
                    builder
                        .http1()
                        .keep_alive(true)
                        .pipeline_flush(true);
                    {
                        let mut http2 = builder.http2();
                        if let Some(value) =
                            builder_state.config.http2_max_concurrent_streams
                        {
                            http2.max_concurrent_streams(value);
                        }
                        if let Some(value) =
                            builder_state.config.http2_initial_window_size
                        {
                            http2.initial_stream_window_size(value);
                            http2.initial_connection_window_size(value);
                        }
                        if let Some(value) =
                            builder_state.config.http2_keep_alive_interval
                        {
                            http2.keep_alive_interval(value);
                        }
                        if let Some(value) =
                            builder_state.config.http2_keep_alive_timeout
                        {
                            http2.keep_alive_timeout(value);
                        }
                    }
                    let _ = builder.serve_connection(io, service).await;
                });
            }
        }
    }

    Ok(())
}

struct ChannelBody {
    receiver: mpsc::Receiver<Result<Bytes, std::io::Error>>,
}

impl hyper::body::Body for ChannelBody {
    type Data = Bytes;
    type Error = std::io::Error;

    fn poll_frame(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        match self.get_mut().receiver.poll_recv(cx) {
            Poll::Ready(Some(Ok(data))) => Poll::Ready(Some(Ok(Frame::data(data)))),
            Poll::Ready(Some(Err(error))) => Poll::Ready(Some(Err(error))),
            Poll::Ready(None) => Poll::Ready(None),
            Poll::Pending => Poll::Pending,
        }
    }
}

enum ResponseBody {
    Full(Full<Bytes>),
    Channel(ChannelBody),
}

impl hyper::body::Body for ResponseBody {
    type Data = Bytes;
    type Error = std::io::Error;

    fn poll_frame(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        match self.get_mut() {
            ResponseBody::Full(body) => Pin::new(body)
                .poll_frame(cx)
                .map_err(|never| match never {}),
            ResponseBody::Channel(body) => Pin::new(body).poll_frame(cx),
        }
    }

    fn size_hint(&self) -> hyper::body::SizeHint {
        match self {
            ResponseBody::Full(body) => body.size_hint(),
            ResponseBody::Channel(_) => hyper::body::SizeHint::default(),
        }
    }

    fn is_end_stream(&self) -> bool {
        match self {
            ResponseBody::Full(body) => body.is_end_stream(),
            ResponseBody::Channel(_) => false,
        }
    }
}

async fn handle_request(
    request: HyperRequest<Incoming>,
    state: Arc<ServerState>,
    client: IpAddr,
    config: ServerConfig,
) -> HyperResponse<ResponseBody> {
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

    let host = parts
        .headers
        .get(HOST)
        .and_then(|value| value.to_str().ok());
    if !host_allowed(host, &state.config.allowed_hosts) {
        return BuiltResponse::framework(StatusCode::BAD_REQUEST, BAD_REQUEST_BODY, &config)
            .into_hyper(false);
    }
    let client = effective_client(
        client,
        &parts.headers,
        &state.config.trusted_proxies,
        state.config.trust_proxy_headers,
    );

    // Route first, so we know exactly which request data the handler needs.
    let matched = match state.router.at(path) {
        Ok(matched) => matched,
        Err(_) => {
            return BuiltResponse::framework(StatusCode::NOT_FOUND, NOT_FOUND_BODY, &config)
                .into_hyper(false)
        }
    };
    let path_id = *matched.value;

    let methods = &state.paths[path_id];

    // Automatic OPTIONS response.
    if method == Method::OPTIONS && !methods.contains_key(&Method::OPTIONS) {
        let allow = allow_header(methods);
        return BuiltResponse::framework_empty(
            StatusCode::NO_CONTENT,
            vec![("allow".to_string(), allow)],
            &config,
        )
        .into_hyper(false);
    }

    let route_index = match methods.get(&method) {
        Some(index) => *index,
        None if method == Method::HEAD => match methods.get(&Method::GET) {
            Some(index) => *index,
            None => return method_not_allowed(methods, &config),
        },
        None => return method_not_allowed(methods, &config),
    };

    let spec = &state.routes[route_index].spec;
    let has_handlers = !state.exception_handlers.is_empty();
    // A request object is needed if the handler declares one, or if a custom
    // exception handler might need to inspect it.
    let full_request = spec.needs_request || has_handlers;
    let needs_headers = full_request || spec.has_header_params;
    let needs_query = full_request || spec.has_query_params;
    let needs_body = full_request || spec.has_body;

    let params = if (spec.has_path_params || full_request) && !matched.params.is_empty() {
        let mut params = Vec::with_capacity(matched.params.len());
        for (key, value) in matched.params.iter() {
            params.push((key.to_string(), value.to_string()));
        }
        params
    } else {
        Vec::new()
    };

    // Reject oversized payloads from Content-Length without reading a frame.
    if needs_body {
        if let Some(length) = parts
            .headers
            .get(CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<u64>().ok())
        {
            if length > state.max_body_size as u64 {
                return BuiltResponse::framework(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    PAYLOAD_TOO_LARGE_BODY,
                    &config,
                )
                .into_hyper(false);
            }
        }
    }

    // Only materialize the pieces the route actually asked for.
    let path_string = full_request.then(|| path.to_string());
    let query_string = full_request.then(|| query.to_string());
    let query_map = needs_query.then(|| parse_query(query));
    let headers = if needs_headers {
        Some(parts.headers)
    } else {
        None
    };

    let body = if !needs_body {
        // Drain in the background so the connection can be reused, but avoid
        // buffering data that no view or exception handler will inspect.
        if !incoming.is_end_stream() {
            let max_size = state.max_body_size;
            tokio::spawn(async move {
                let mut incoming = incoming;
                // Discard the payload, but never read more than the
                // configured body limit: an unbounded drain on a cheap
                // route would be a bandwidth/CPU DoS vector.
                let mut total = 0usize;
                while let Some(frame) = incoming.frame().await {
                    match frame {
                        Ok(frame) => {
                            total += frame.into_data().map(Bytes::len).unwrap_or(0);
                        }
                        Err(_) => break,
                    }
                    if total > max_size {
                        break;
                    }
                }
            });
        }
        Bytes::new()
    } else if incoming.is_end_stream() {
        Bytes::new()
    } else {
        match read_body(incoming, state.max_body_size).await {
            Ok(body) => body,
            Err(BodyError::TooLarge) => {
                return BuiltResponse::framework(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    PAYLOAD_TOO_LARGE_BODY,
                    &config,
                )
                .into_hyper(false)
            }
            Err(BodyError::Read) => {
                return BuiltResponse::framework(
                    StatusCode::BAD_REQUEST,
                    BAD_REQUEST_BODY,
                    &config,
                )
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
    let mut built = dispatch(state.clone(), route_index, request_data).await;
    apply_security_headers(&mut built, &state.config);
    let status = built.status;
    let response = built.into_hyper(is_head);
    if state.access_log {
        let elapsed = started.elapsed().as_secs_f64() * 1000.0;
        if state.config.access_log_json {
            eprintln!(
                "{{\"method\":\"{}\",\"path\":\"{}\",\"status\":{},\"duration_ms\":{:.2}}}",
                method,
                escape_log(log_path.as_deref().unwrap_or("")),
                status.as_u16(),
                elapsed
            );
        } else {
            eprintln!(
                "{} {} {} {:.2}ms",
                method,
                log_path.as_deref().unwrap_or(""),
                status.as_u16(),
                elapsed
            );
        }
    }
    response
}

/// Split a `Host` header value into its hostname, removing any port and
/// bracket quoting so that IPv6 literals (`[::1]`, `[::1]:8000`) work.
fn strip_host_port(host: &str) -> &str {
    let host = host.trim();
    if let Some(rest) = host.strip_prefix('[') {
        // Bracketed IPv6 literal: the port (if present) follows `]`.
        return rest.split(']').next().unwrap_or("");
    }
    // A bare colon can only introduce a port here (a raw IPv6 address must
    // be bracketed in a Host header), so split at most once from the right.
    match host.split_once(':') {
        Some((name, _)) => name,
        None => host,
    }
}

fn host_allowed(host: Option<&str>, allowed_hosts: &[String]) -> bool {
    if allowed_hosts.iter().any(|pattern| pattern == "*") {
        return true;
    }
    let Some(host) = host else {
        return false;
    };
    let hostname = strip_host_port(host).to_ascii_lowercase();
    allowed_hosts.iter().any(|pattern| {
        let pattern = pattern.to_ascii_lowercase();
        if let Some(suffix) = pattern.strip_prefix('.') {
            hostname == suffix || hostname.ends_with(&pattern)
        } else {
            hostname == pattern
        }
    })
}

fn effective_client(
    client: IpAddr,
    headers: &HeaderMap,
    trusted_proxies: &[String],
    trust_proxy_headers: bool,
) -> IpAddr {
    // Proxy headers are only consulted when explicitly enabled; otherwise the
    // peer address is authoritative even behind a trusted proxy (this matches
    // HttpRequest.is_secure(), which already honors TRUST_PROXY_HEADERS).
    if !trust_proxy_headers {
        return client;
    }
    let trusted = trusted_proxies.iter().any(|proxy| {
        proxy == "*"
            || proxy
                .parse::<IpAddr>()
                .map(|ip| ip == client)
                .unwrap_or(false)
    });
    if trusted {
        if let Some(forwarded) = headers
            .get("x-forwarded-for")
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.split(',').next())
            .and_then(|value| value.trim().parse::<IpAddr>().ok())
        {
            return forwarded;
        }
    }
    client
}

fn apply_security_headers(response: &mut BuiltResponse, config: &ServerConfig) {
    if !config.security_headers {
        return;
    }
    response.add_header_if_missing("x-content-type-options", "nosniff");
    response.add_header_if_missing("x-frame-options", &config.x_frame_options);
    response.add_header_if_missing("referrer-policy", &config.referrer_policy);
    if config.hsts_seconds > 0 {
        let mut value = format!("max-age={}", config.hsts_seconds);
        if config.hsts_include_subdomains {
            value.push_str("; includeSubDomains");
        }
        response.add_header_if_missing("strict-transport-security", &value);
    }
}

fn escape_log(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

enum BodyError {
    TooLarge,
    Read,
}

/// Collect a request body with a size limit.
///
/// The common case (one data frame) is returned without copying: the frame's
/// `Bytes` buffer is used directly.  For multiple frames, only the second frame
/// is copied once; the remaining frames are appended to a geometrically growing
/// `BytesMut`, so total work stays linear in the body size.
async fn read_body(mut body: Incoming, max_size: usize) -> Result<Bytes, BodyError> {
    let mut first: Option<Bytes> = None;
    let mut combined: Option<BytesMut> = None;
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

        if let Some(buffer) = combined.as_mut() {
            // BytesMut grows geometrically, so extending once per frame is
            // amortized linear in the total body size.
            buffer.extend_from_slice(&data);
        } else {
            match first.take() {
                None => first = Some(data),
                Some(existing) => {
                    // Only the second frame forces a copy. Afterwards the
                    // BytesMut absorbs all remaining frames without
                    // re-copying the data collected so far.
                    let mut merged = BytesMut::with_capacity(total);
                    merged.extend_from_slice(&existing);
                    merged.extend_from_slice(&data);
                    combined = Some(merged);
                }
            }
        }
    }

    Ok(match combined {
        Some(buffer) => buffer.freeze(),
        None => first.unwrap_or_default(),
    })
}

fn method_not_allowed(
    methods: &HashMap<Method, usize>,
    config: &ServerConfig,
) -> HyperResponse<ResponseBody> {
    let allow = allow_header(methods);
    BuiltResponse::framework(
        StatusCode::METHOD_NOT_ALLOWED,
        METHOD_NOT_ALLOWED_BODY,
        config,
    )
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

#[derive(Clone)]
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
        return dispatch_async(state, route_index, request).await;
    }

    if state.config.offload_sync_views {
        let task_state = state.clone();
        let handle = tokio::task::spawn_blocking(move || {
            let result =
                Python::attach(|py| call_handler(py, &task_state.routes[route_index], &request));
            match result {
                Ok(value) => Ok(Python::attach(|py| {
                    let status = task_state.routes[route_index].spec.status_code;
                    serialize_result(py, value, status, task_state.event_loop.as_ref())
                })),
                Err(CallError::Validation(failure)) => Ok(validation_response(failure)),
                Err(CallError::Python(error)) => Err((error, request)),
            }
        })
        .await;

        return match handle {
            Ok(Ok(response)) => response,
            Ok(Err((error, request))) => handle_python_error(&state, error, &request).await,
            Err(error) => {
                eprintln!("handler task failed: {error}");
                BuiltResponse::static_json(StatusCode::INTERNAL_SERVER_ERROR, INTERNAL_ERROR_BODY)
            }
        };
    }

    // Run short synchronous handlers directly on the current worker.  The GIL
    // serializes Python execution anyway, so a thread-pool round-trip only adds
    // latency unless the application opts into offloading.
    dispatch_sync(&state, route_index, &request).await
}

async fn dispatch_sync(
    state: &Arc<ServerState>,
    route_index: usize,
    request: &RequestData,
) -> BuiltResponse {
    let status = state.routes[route_index].spec.status_code;
    let result = Python::attach(|py| call_handler(py, &state.routes[route_index], request));
    match result {
        Ok(value) => {
            Python::attach(|py| serialize_result(py, value, status, state.event_loop.as_ref()))
        }
        Err(CallError::Validation(failure)) => validation_response(failure),
        Err(CallError::Python(error)) => handle_python_error(state, error, request).await,
    }
}

async fn dispatch_async(
    state: Arc<ServerState>,
    route_index: usize,
    request: RequestData,
) -> BuiltResponse {
    // Calling an `async def` handler only creates a coroutine, so it is cheap
    // enough to do inline instead of paying for a blocking-pool round-trip.
    let awaitable = match Python::attach(|py| {
        call_handler(py, &state.routes[route_index], &request)
    }) {
        Ok(awaitable) => awaitable,
        Err(CallError::Validation(failure)) => return validation_response(failure),
        Err(CallError::Python(error)) => return handle_python_error(&state, error, &request).await,
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
        Err(error) => return handle_python_error(&state, error, &request).await,
    };

    match future.await {
        Ok(value) => Python::attach(|py| {
            let status = state.routes[route_index].spec.status_code;
            serialize_result(py, value, status, state.event_loop.as_ref())
        }),
        Err(error) => handle_python_error(&state, error, &request).await,
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

async fn handle_python_error(
    state: &ServerState,
    error: PyErr,
    request: &RequestData,
) -> BuiltResponse {
    // User supplied exception handlers take precedence so applications can
    // override the built-in HTTPException rendering.
    for (exc_type, handler) in &state.exception_handlers {
        let call = Python::attach(|py| -> Option<Result<Py<PyAny>, PyErr>> {
            if !error.is_instance(py, exc_type.bind(py)) {
                return None;
            }
            let request_object = match Py::new(py, request.to_request()) {
                Ok(request) => request.into_any(),
                Err(inner) => return Some(Err(inner)),
            };
            let exception = error.value(py).clone().into_any().unbind();
            Some(handler.call1(py, (request_object, exception)))
        });

        let value = match call {
            None => continue,
            Some(Ok(value)) => value,
            Some(Err(handler_error)) => {
                Python::attach(|py| handler_error.print(py));
                break;
            }
        };

        let is_awaitable = Python::attach(|py| -> PyResult<bool> {
            let inspect = py.import("inspect")?;
            inspect
                .call_method1("isawaitable", (value.bind(py),))?
                .is_truthy()
        })
        .unwrap_or(false);

        let result = if is_awaitable {
            let event_loop = match &state.event_loop {
                Some(event_loop) => event_loop.clone(),
                None => {
                    return BuiltResponse::static_json(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        INTERNAL_ERROR_BODY,
                    )
                }
            };
            let future = match Python::attach(|py| event_loop.future(value.bind(py).clone())) {
                Ok(future) => future,
                Err(handler_error) => {
                    Python::attach(|py| handler_error.print(py));
                    break;
                }
            };
            future.await
        } else {
            Ok(value)
        };

        match result {
            Ok(value) => {
                return Python::attach(|py| {
                    serialize_result(py, value, 200, state.event_loop.as_ref())
                })
            }
            Err(handler_error) => {
                Python::attach(|py| handler_error.print(py));
                break;
            }
        }
    }

    // Built-in HTTPException support.
    let mut builtin = None;
    Python::attach(|py| {
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

                builtin = Some(BuiltResponse::json_vec(
                    StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                    body,
                    headers,
                ));
            }
        }
    });
    if let Some(response) = builtin {
        return response;
    }

    Python::attach(|py| {
        if state.config.debug {
            if let Ok(module) = py.import("alphaapi._debug") {
                if let Ok(html) = module.call_method1("format_exception", (error.value(py),)) {
                    if let Ok(text) = html.extract::<String>() {
                        return BuiltResponse {
                            status: StatusCode::INTERNAL_SERVER_ERROR,
                            headers: Vec::new(),
                            body: Bytes::from(text.into_bytes()),
                            stream: None,
                            media_type: Some(Cow::Borrowed("text/html; charset=utf-8")),
                        };
                    }
                }
            }
        }
        error.print(py);
        BuiltResponse::static_json(StatusCode::INTERNAL_SERVER_ERROR, INTERNAL_ERROR_BODY)
    })
}

fn serialize_result(
    py: Python<'_>,
    value: Py<PyAny>,
    default_status: u16,
    event_loop: Option<&Arc<PyLoop>>,
) -> BuiltResponse {
    let value = value.bind(py);

    if let Ok(stream) = value.getattr("__alphaapi_stream__") {
        if !stream.is_none() {
            let response = Response::from_instance(value);
            let (status, headers, media_type) = match response {
                Some(response) => (
                    StatusCode::from_u16(response.status_code)
                        .unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
                    response.headers,
                    response.media_type.map(Cow::Owned),
                ),
                None => (
                    StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
                    Vec::new(),
                    None,
                ),
            };
            match build_python_stream(py, &stream, event_loop.cloned()) {
                Ok(channel) => {
                    return BuiltResponse {
                        status,
                        headers,
                        body: Bytes::new(),
                        stream: Some(channel),
                        media_type,
                    }
                }
                Err(error) => {
                    error.print(py);
                    return BuiltResponse::static_json(
                        StatusCode::INTERNAL_SERVER_ERROR,
                        INTERNAL_ERROR_BODY,
                    );
                }
            }
        }
    }

    if let Some(response) = Response::from_instance(value) {
        let status =
            StatusCode::from_u16(response.status_code).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
        return BuiltResponse {
            status,
            headers: response.headers,
            body: Bytes::from(response.body),
            stream: None,
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
            stream: None,
            media_type: Some(Cow::Borrowed("application/octet-stream")),
        };
    }

    if let Ok(bytes) = value.cast::<PyByteArray>() {
        return BuiltResponse {
            status: StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            headers: Vec::new(),
            body: Bytes::from(bytes.to_vec()),
            stream: None,
            media_type: Some(Cow::Borrowed("application/octet-stream")),
        };
    }

    if let Ok(text) = value.cast::<PyString>() {
        return BuiltResponse {
            status: StatusCode::from_u16(default_status).unwrap_or(StatusCode::OK),
            headers: Vec::new(),
            body: Bytes::from(text.to_string_lossy().into_owned().into_bytes()),
            stream: None,
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

fn stream_item_bytes(py: Python<'_>, item: &Bound<'_, PyAny>) -> PyResult<Bytes> {
    if let Ok(bytes) = item.cast::<PyBytes>() {
        return Ok(Bytes::copy_from_slice(bytes.as_bytes()));
    }
    if let Ok(text) = item.cast::<PyString>() {
        return Ok(Bytes::from(
            text.to_string_lossy().into_owned().into_bytes(),
        ));
    }
    Ok(Bytes::from(crate::util::content_to_bytes(py, item)?))
}

fn build_python_stream(
    _py: Python<'_>,
    value: &Bound<'_, PyAny>,
    event_loop: Option<Arc<PyLoop>>,
) -> PyResult<ChannelBody> {
    let (sender, receiver) = mpsc::channel(8);

    if value.hasattr("__aiter__")? {
        let iterator = value.call_method0("__aiter__")?.unbind();
        let event_loop = event_loop.ok_or_else(|| {
            PyRuntimeError::new_err("async streaming requires the asyncio bridge")
        })?;

        enum Step {
            Awaitable(Py<PyAny>),
            Stop,
            Error(String),
        }

        tokio::spawn(async move {
            loop {
                // Bound Python objects stay inside `attach`; only owned,
                // `Send` handles cross the await points below.
                let step = Python::attach(|py| match iterator.bind(py).call_method0("__anext__") {
                    Ok(awaitable) => Step::Awaitable(awaitable.unbind()),
                    Err(error) => {
                        if error.is_instance_of::<PyStopAsyncIteration>(py) {
                            Step::Stop
                        } else {
                            Step::Error(error.to_string())
                        }
                    }
                });

                let awaitable = match step {
                    Step::Awaitable(awaitable) => awaitable,
                    Step::Stop => break,
                    Step::Error(message) => {
                        let _ = sender.send(Err(std::io::Error::other(message))).await;
                        break;
                    }
                };

                let future =
                    match Python::attach(|py| event_loop.future(awaitable.bind(py).clone())) {
                        Ok(future) => future,
                        Err(error) => {
                            let _ = sender
                                .send(Err(std::io::Error::other(error.to_string())))
                                .await;
                            break;
                        }
                    };

                match future.await {
                    Ok(item) => {
                        let bytes = Python::attach(|py| stream_item_bytes(py, item.bind(py)));
                        match bytes {
                            Ok(bytes) => {
                                if sender.send(Ok(bytes)).await.is_err() {
                                    break;
                                }
                            }
                            Err(error) => {
                                let _ = sender
                                    .send(Err(std::io::Error::other(error.to_string())))
                                    .await;
                                break;
                            }
                        }
                    }
                    Err(error) => {
                        let stop =
                            Python::attach(|py| error.is_instance_of::<PyStopAsyncIteration>(py));
                        if !stop {
                            let _ = sender
                                .send(Err(std::io::Error::other(error.to_string())))
                                .await;
                        }
                        break;
                    }
                }
            }
        });
    } else {
        let iterator = value.try_iter()?.unbind();
        enum SyncStep {
            Item(Py<PyAny>),
            Stop,
            Error(String),
        }

        tokio::task::spawn_blocking(move || loop {
            let step = Python::attach(|py| {
                let mut iterator = iterator.bind(py).clone();
                match iterator.next() {
                    None => SyncStep::Stop,
                    Some(Ok(item)) => SyncStep::Item(item.unbind()),
                    Some(Err(error)) => {
                        if error.is_instance_of::<PyStopIteration>(py) {
                            SyncStep::Stop
                        } else {
                            SyncStep::Error(error.to_string())
                        }
                    }
                }
            });

            match step {
                SyncStep::Stop => break,
                SyncStep::Item(item) => {
                    let bytes = Python::attach(|py| stream_item_bytes(py, item.bind(py)));
                    match bytes {
                        Ok(bytes) => {
                            if sender.blocking_send(Ok(bytes)).is_err() {
                                break;
                            }
                        }
                        Err(error) => {
                            let _ =
                                sender.blocking_send(Err(std::io::Error::other(error.to_string())));
                            break;
                        }
                    }
                }
                SyncStep::Error(message) => {
                    let _ = sender.blocking_send(Err(std::io::Error::other(message)));
                    break;
                }
            }
        });
    }

    Ok(ChannelBody { receiver })
}

// ---------------------------------------------------------------------------
// HTTP responses
// ---------------------------------------------------------------------------

struct BuiltResponse {
    status: StatusCode,
    headers: Vec<(String, String)>,
    body: Bytes,
    stream: Option<ChannelBody>,
    media_type: Option<Cow<'static, str>>,
    /// Security configuration captured at construction time.  When present,
    /// `into_hyper` applies the security headers itself, so *every* response
    /// path — including framework early returns such as host rejections,
    /// router 404s, 405s and automatic OPTIONS — carries them.  Views that
    /// build responses through Python do not set this field; those get the
    /// headers applied in `handle_request` exactly as before.
    security: Option<ServerConfig>,
}

impl BuiltResponse {
    fn json(status: StatusCode, body: Bytes, headers: Vec<(String, String)>) -> Self {
        Self {
            status,
            headers,
            body,
            stream: None,
            media_type: Some(Cow::Borrowed("application/json")),
            security: None,
        }
    }

    fn json_vec(status: StatusCode, body: Vec<u8>, headers: Vec<(String, String)>) -> Self {
        Self::json(status, Bytes::from(body), headers)
    }

    fn static_json(status: StatusCode, body: &'static [u8]) -> Self {
        Self::json(status, Bytes::from_static(body), Vec::new())
    }

    /// Framework-generated response (404/405/413/503/…).  Carrying the
    /// server config guarantees the security headers are applied even on
    /// early-return paths that never reach the post-dispatch header pass.
    fn framework(status: StatusCode, body: &'static [u8], config: &ServerConfig) -> Self {
        Self {
            security: Some(config.clone()),
            ..Self::static_json(status, body)
        }
    }

    fn empty(status: StatusCode, headers: Vec<(String, String)>) -> Self {
        Self {
            status,
            headers,
            body: Bytes::new(),
            stream: None,
            media_type: None,
            security: None,
        }
    }

    fn framework_empty(status: StatusCode, headers: Vec<(String, String)>, config: &ServerConfig) -> Self {
        Self {
            security: Some(config.clone()),
            ..Self::empty(status, headers)
        }
    }

    fn with_header(mut self, key: &str, value: String) -> Self {
        self.headers.push((key.to_string(), value));
        self
    }

    fn add_header_if_missing(&mut self, key: &str, value: &str) {
        if !self
            .headers
            .iter()
            .any(|(name, _)| name.eq_ignore_ascii_case(key))
        {
            self.headers.push((key.to_string(), value.to_string()));
        }
    }

    fn into_hyper(self, head: bool) -> HyperResponse<ResponseBody> {
        let status = self.status;
        let no_body = status == StatusCode::NO_CONTENT || status == StatusCode::NOT_MODIFIED;
        let full_length = if self.stream.is_none() && !no_body {
            Some(self.body.len())
        } else {
            None
        };
        let mut built = Self {
            status: self.status,
            headers: self.headers,
            body: self.body,
            stream: self.stream,
            media_type: self.media_type,
            security: None,
        };
        if let Some(config) = &self.security {
            apply_security_headers(&mut built, config);
        }
        let body = if head || no_body {
            ResponseBody::Full(Full::new(Bytes::new()))
        } else {
            match built.stream {
                Some(channel) => ResponseBody::Channel(channel),
                None => ResponseBody::Full(Full::new(built.body)),
            }
        };

        let mut response = HyperResponse::new(body);
        *response.status_mut() = status;
        let headers = response.headers_mut();

        for (key, value) in &built.headers {
            if let (Ok(name), Ok(value)) = (
                HeaderName::from_bytes(key.as_bytes()),
                HeaderValue::from_str(value),
            ) {
                headers.append(name, value);
            }
        }

        if !headers.contains_key(CONTENT_TYPE) {
            if let Some(media_type) = &built.media_type {
                if let Ok(value) = HeaderValue::from_str(media_type.as_ref()) {
                    headers.insert(CONTENT_TYPE, value);
                }
            }
        }

        if let Some(length) = full_length {
            if !headers.contains_key(CONTENT_LENGTH) {
                let mut buffer = itoa::Buffer::new();
                if let Ok(value) = HeaderValue::from_str(buffer.format(length)) {
                    headers.insert(CONTENT_LENGTH, value);
                }
            }
        }

        if !headers.contains_key(SERVER) {
            headers.insert(SERVER, HeaderValue::from_static("alphaapi"));
        }

        response
    }
}
